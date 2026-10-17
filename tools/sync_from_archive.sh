#!/usr/bin/env bash
# Применяет архив поставки к рабочей копии репозитория.
#
# Использование: tools/sync_from_archive.sh <путь к obfuscator-<версия>.zip>
#
# Порядок:
#   1. Проверки до любых изменений: чистая рабочая копия, ветка из .ai/delivery.env, HEAD = тег sdd/<base>,
#      файлы владельца игнорируются git.
#   2. Показ списка удаляемых, изменяемых и новых файлов и подтверждение с терминала.
#   3. Синхронизация: только файлы, отслеживаемые git; игнорируемые git и исключённые файлы не трогаются.
#
# Любая остановка — ненулевой код выхода, чтобы следующие команды цепочки (&&) не выполнялись.

set -euo pipefail

# --- Списки исключений --------------------------------------------------------------------------------------------
# Шаблон с "/" в начале относится только к корню репозитория; без него — к части пути на любой глубине.

# Служебные каталоги и кэши.
SERVICE_EXCLUDES=("/.git" "/.venv" "__pycache__" ".pytest_cache" ".ruff_cache" ".hypothesis" ".mypy_cache"
                  "*.egg-info" "/dist" "/build")
# Файлы, которые порождаются на стороне владельца и коммитятся им (uv sync).
GENERATED_EXCLUDES=("/uv.lock")
# Файлы владельца: не попадают в архивы, обязаны игнорироваться git.
USER_EXCLUDES=("/.idea" "/dictionary.toml" "/dictionaries" "/runs" "/logs" "*.obfstate")
# Пути для проверки git check-ignore (каталоги — с "/" в конце).
USER_IGNORE_PROBES=(".idea/" "dictionary.toml" "dictionary.sample.toml" "dictionaries/" "dictionaries/sample.toml"
                    "runs/" "logs/" "sample.obfstate/")

ALL_EXCLUDES=("${SERVICE_EXCLUDES[@]}" "${GENERATED_EXCLUDES[@]}" "${USER_EXCLUDES[@]}")

die() {
    printf 'ОСТАНОВКА: %s\n' "$1" >&2
    shift
    for line in "$@"; do printf '  %s\n' "$line" >&2; done
    exit 1
}

# is_excluded <относительный путь> — 0, если путь попадает под исключения.
is_excluded() {
    local rel="$1" pat root comp
    local -a parts
    for pat in "${ALL_EXCLUDES[@]}"; do
        if [[ "$pat" == /* ]]; then
            root="${pat#/}"
            # shellcheck disable=SC2053  # шаблон намеренно без кавычек
            if [[ "$rel" == $root || "$rel" == $root/* ]]; then return 0; fi
        else
            IFS='/' read -r -a parts <<< "$rel"
            for comp in "${parts[@]}"; do
                # shellcheck disable=SC2053
                if [[ "$comp" == $pat ]]; then return 0; fi
            done
        fi
    done
    return 1
}

# exec_bits <файл> — биты исполнения из прав (x/-) владельца, группы, остальных. Не [[ -x ]]: он проверяет право
# запуска и врёт на файловых системах с noexec (например, /tmp), где распаковывается архив.
exec_bits() {
    local mode
    mode="$(stat -c %A -- "$1")"
    printf '%s%s%s' "${mode:3:1}" "${mode:6:1}" "${mode:9:1}"
}

# --- Аргументы и окружение ----------------------------------------------------------------------------------------

[[ $# -eq 1 ]] || die "нужен один аргумент — путь к архиву поставки" \
    "пример: tools/sync_from_archive.sh ~/Загрузки/obfuscator-0.0.1.zip"
ARCHIVE="$(realpath -- "$1")"
[[ -f "$ARCHIVE" ]] || die "архив не найден: $1"
command -v unzip >/dev/null || die "не найдена программа unzip" "установите: sudo apt install unzip"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || die "запустите скрипт внутри репозитория obfuscator"
cd "$REPO"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

unzip -q "$ARCHIVE" -d "$TMP/unpacked"
mapfile -t TOP < <(find "$TMP/unpacked" -mindepth 1 -maxdepth 1)
[[ ${#TOP[@]} -eq 1 && -d "${TOP[0]}" ]] || die "в архиве должен быть ровно один каталог верхнего уровня"
SRC="${TOP[0]}"
[[ -f "$SRC/.ai/delivery.env" ]] || die "в архиве нет .ai/delivery.env"

# --- .ai/delivery.env читается как текст, без source ---------------------------------------------------------------

VERSION="" BASE="" BRANCH=""
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
        version) VERSION="$value" ;;
        base) BASE="$value" ;;
        branch) BRANCH="$value" ;;
        *) die "неизвестный ключ в .ai/delivery.env: $key" ;;
    esac
done < "$SRC/.ai/delivery.env"

SEMVER='^[0-9]+\.[0-9]+\.[0-9]+$'
[[ "$VERSION" =~ $SEMVER ]] || die "неверная version в .ai/delivery.env: '$VERSION'"
[[ "$BASE" == "none" || "$BASE" =~ $SEMVER ]] || die "неверный base в .ai/delivery.env: '$BASE'"
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || die "неверный branch в .ai/delivery.env: '$BRANCH'"
grep -qx "version = \"$VERSION\"" "$SRC/pyproject.toml" \
    || die "версия в pyproject.toml архива не равна $VERSION — архив собран неверно, сообщите ассистенту"

echo "Поставка $VERSION (база: $BASE, ветка: $BRANCH)"

# --- Проверки до изменений ----------------------------------------------------------------------------------------

# Неотслеживаемые файлы владельца из исключений допускаются: до первой поставки .gitignore их ещё не игнорирует.
DIRTY=()
while IFS= read -r -d '' entry; do
    status="${entry:0:2}"
    path="${entry:3}"
    if [[ "$status" == "??" ]] && is_excluded "${path%/}"; then continue; fi
    DIRTY+=("$entry")
done < <(git status --porcelain -z --untracked-files=normal)
[[ ${#DIRTY[@]} -eq 0 ]] || die "рабочая копия не чистая:" "${DIRTY[@]}" \
    "закоммитьте свои изменения или уберите их (git stash -u), затем повторите команду"

CURRENT_BRANCH="$(git branch --show-current)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] \
    || die "текущая ветка '$CURRENT_BRANCH', а поставка для '$BRANCH'" "переключитесь: git switch $BRANCH"

APPLIED_COMMIT="$(git rev-parse -q --verify "refs/tags/sdd/$VERSION^{commit}" || true)"
if [[ -n "$APPLIED_COMMIT" ]]; then
    if [[ "$APPLIED_COMMIT" == "$(git rev-parse HEAD)" ]]; then
        die "поставка $VERSION уже применена: тег sdd/$VERSION стоит на HEAD — делать ничего не нужно"
    fi
    die "тег sdd/$VERSION уже есть, но не на HEAD — поставка $VERSION применялась раньше" \
        "сообщите ассистенту вывод: git log --oneline -3 sdd/$VERSION"
fi

if [[ "$BASE" != "none" ]]; then
    BASE_COMMIT="$(git rev-parse -q --verify "refs/tags/sdd/$BASE^{commit}" || true)"
    [[ -n "$BASE_COMMIT" ]] || die "нет тега sdd/$BASE — предыдущая поставка не применена" \
        "примените поставку $BASE или сообщите ассистенту"
    if [[ "$BASE_COMMIT" != "$(git rev-parse HEAD)" ]] \
        && git merge-base --is-ancestor "$BASE_COMMIT" HEAD \
        && git diff --quiet "$BASE_COMMIT" HEAD --; then
        echo "После поставки $BASE есть коммиты без изменений файлов (например, слияние) — продолжаю:"
        git --no-pager log --oneline --no-color "sdd/$BASE..HEAD" || true
    elif [[ "$BASE_COMMIT" != "$(git rev-parse HEAD)" ]]; then
        echo "После поставки $BASE в ветке есть коммиты с изменениями файлов:" >&2
        git --no-pager log --oneline --no-color "sdd/$BASE..HEAD" >&2 || true
        die "HEAD не совпадает с поставкой $BASE" \
            "отправьте ассистенту вывод: git diff sdd/$BASE..HEAD" \
            "ассистент перенесёт эти изменения в следующий архив"
    fi
fi

NOT_IGNORED=()
for probe in "${USER_IGNORE_PROBES[@]}"; do
    if ! git -c core.excludesFile="$SRC/.gitignore" check-ignore -q -- "$probe"; then
        NOT_IGNORED+=("$probe")
    fi
done
[[ ${#NOT_IGNORED[@]} -eq 0 ]] || die "файлы владельца не игнорируются git (или отслеживаются):" \
    "${NOT_IGNORED[@]}" "добавьте их в .gitignore или уберите из индекса: git rm --cached <путь>"

# --- План изменений -----------------------------------------------------------------------------------------------

declare -A IN_ARCHIVE=()
ARCHIVE_FILES=()
while IFS= read -r -d '' rel; do
    is_excluded "$rel" && continue
    IN_ARCHIVE["$rel"]=1
    ARCHIVE_FILES+=("$rel")
done < <(cd "$SRC" && find . -mindepth 1 \( -type f -o -type l \) -printf '%P\0' | sort -z)

TO_DELETE=()
while IFS= read -r -d '' rel; do
    is_excluded "$rel" && continue
    [[ -n "${IN_ARCHIVE[$rel]:-}" ]] || TO_DELETE+=("$rel")
done < <(git ls-files -z)

TO_ADD=()
TO_CHANGE=()
CHANGE_NOTE=()
for rel in "${ARCHIVE_FILES[@]}"; do
    if [[ ! -e "$rel" && ! -L "$rel" ]]; then
        TO_ADD+=("$rel")
    elif ! cmp -s "$SRC/$rel" "$rel"; then
        TO_CHANGE+=("$rel")
        CHANGE_NOTE+=("$rel")
    elif [[ "$(exec_bits "$SRC/$rel")" != "$(exec_bits "$rel")" ]]; then
        TO_CHANGE+=("$rel")
        CHANGE_NOTE+=("$rel (только бит исполнения: в архиве $(stat -c %A "$SRC/$rel"), в рабочей копии $(stat -c %A "$rel"))")
    fi
done

if [[ ${#TO_DELETE[@]} -eq 0 && ${#TO_ADD[@]} -eq 0 && ${#TO_CHANGE[@]} -eq 0 ]]; then
    echo "Изменений нет: рабочая копия уже совпадает с архивом."
    exit 0
fi

print_list() {
    local title="$1"
    shift
    [[ $# -eq 0 ]] && return 0
    echo "$title ($#):"
    printf '  %s\n' "$@"
}
print_list "Будут УДАЛЕНЫ" "${TO_DELETE[@]}"
print_list "Будут изменены" "${CHANGE_NOTE[@]}"
print_list "Будут добавлены" "${TO_ADD[@]}"

[[ -r /dev/tty ]] || die "нет терминала для подтверждения (/dev/tty)"
printf 'Применить? [y/N] ' > /dev/tty
read -r ANSWER < /dev/tty
[[ "$ANSWER" == "y" || "$ANSWER" == "Y" || "$ANSWER" == "д" || "$ANSWER" == "Д" ]] \
    || die "отменено пользователем; ничего не изменено"

# --- Синхронизация ------------------------------------------------------------------------------------------------

for rel in "${TO_DELETE[@]}"; do
    rm -f -- "$rel"
    dir="$(dirname -- "$rel")"
    while [[ "$dir" != "." ]] && rmdir -- "$dir" 2>/dev/null; do
        dir="$(dirname -- "$dir")"
    done
done

for rel in "${TO_CHANGE[@]}" "${TO_ADD[@]}"; do
    mkdir -p -- "$(dirname -- "$rel")"
    rm -f -- "$rel"
    cp --preserve=mode -- "$SRC/$rel" "$rel"
done

echo "Готово: удалено ${#TO_DELETE[@]}, изменено ${#TO_CHANGE[@]}, добавлено ${#TO_ADD[@]}."
