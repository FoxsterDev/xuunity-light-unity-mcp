#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WRAPPER="${XUUNITY_LIGHT_UNITY_MCP_WRAPPER:-$OPS_ROOT/xuunity_light_unity_mcp.sh}"

PROJECT_ROOT=""
OPEN_EDITOR="true"
RUN_MODE="all"
TIMEOUT_MS="240000"
UNITY_ARGS=()
PLANNED_ASSEMBLIES=()
TMP_DIR=""
MANIFEST_BACKUP=""
MANIFEST_WAS_PATCHED="false"

usage() {
  cat <<'EOF'
Usage:
  run_package_self_tests.sh \
    --project-root /path/to/UnityProject \
    [--mode all|editmode|playmode|fast|scene|lifecycle] \
    [--timeout-ms 240000] \
    [--unity-arg VALUE ...] \
    [--no-open-editor]

Runs the public XUUnity Light MCP package self-tests shipped inside
com.xuunity.light-mcp. These tests are intended to work in an otherwise empty
Unity project after the package is installed.

Unity discovers package test assemblies only when the package name is listed in
the consumer project's Packages/manifest.json testables array. This runner adds
com.xuunity.light-mcp to testables temporarily, refreshes the project, runs the
selected tests, and restores the original manifest on exit.
EOF
}

fail_usage() {
  echo "$1" >&2
  usage >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      shift
      [[ $# -gt 0 ]] || fail_usage "--project-root requires a value"
      PROJECT_ROOT="$1"
      ;;
    --mode)
      shift
      [[ $# -gt 0 ]] || fail_usage "--mode requires a value"
      RUN_MODE="$1"
      ;;
    --timeout-ms)
      shift
      [[ $# -gt 0 ]] || fail_usage "--timeout-ms requires a value"
      TIMEOUT_MS="$1"
      ;;
    --unity-arg)
      shift
      [[ $# -gt 0 ]] || fail_usage "--unity-arg requires a value"
      UNITY_ARGS+=("$1")
      ;;
    --no-open-editor)
      OPEN_EDITOR="false"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail_usage "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$PROJECT_ROOT" ]] || fail_usage "missing required argument: --project-root"
TMP_DIR="$(mktemp -d)"
MANIFEST_PATH="$PROJECT_ROOT/Packages/manifest.json"
MANIFEST_BACKUP="$TMP_DIR/manifest.json"
ASSEMBLY_PLAN_PATH="$TMP_DIR/assembly_plan.tsv"

remove_generated_test_root() {
  local generated_root="$PROJECT_ROOT/Assets/XUUnityLightMcpGenerated"
  [[ -d "$generated_root" ]] || return 0
  rmdir "$generated_root" 2>/dev/null || return 0
  rm -f "$generated_root.meta"
}

cleanup() {
  remove_generated_test_root
  if [[ "$MANIFEST_WAS_PATCHED" == "true" && -f "$MANIFEST_BACKUP" ]]; then
    cp "$MANIFEST_BACKUP" "$MANIFEST_PATH"
    "$WRAPPER" request-project-refresh --project-root "$PROJECT_ROOT" --timeout-ms 180000 >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

enable_package_tests() {
  [[ -f "$MANIFEST_PATH" ]] || fail_usage "Unity project manifest not found: $MANIFEST_PATH"
  cp "$MANIFEST_PATH" "$MANIFEST_BACKUP"
  python3 - "$MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
testables = data.get("testables")
if not isinstance(testables, list):
    testables = []
if "com.xuunity.light-mcp" not in testables:
    testables.append("com.xuunity.light-mcp")
    data["testables"] = testables
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("patched")
else:
    print("already_enabled")
PY
}

print_package_self_test_discovery() {
  local lock_path="$PROJECT_ROOT/Packages/packages-lock.json"
  python3 - "$MANIFEST_PATH" "$lock_path" "$PROJECT_ROOT" "$OPS_ROOT" "$RUN_MODE" "$ASSEMBLY_PLAN_PATH" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
project_root = Path(sys.argv[3])
ops_root = Path(sys.argv[4])
run_mode = sys.argv[5]
plan_path = Path(sys.argv[6])


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_package_source(manifest, manifest_path, project_root, ops_root):
    dependency = str((manifest.get("dependencies") or {}).get("com.xuunity.light-mcp") or "")
    candidates = []

    if dependency.startswith("file:"):
        relative_path = dependency[len("file:") :]
        candidates.append((manifest_path.parent / relative_path).resolve())

    cache_root = project_root / "Library" / "PackageCache"
    if cache_root.is_dir():
        candidates.extend(
            sorted(
                (path for path in cache_root.glob("com.xuunity.light-mcp@*") if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )

    candidates.append(ops_root / "packages" / "com.xuunity.light-mcp")
    for candidate in candidates:
        if (candidate / "Tests").is_dir():
            return candidate
    return candidates[0] if candidates else Path()


def asmdef_name(path):
    data = read_json(path)
    return str(data.get("name") or path.stem)


manifest = read_json(manifest_path)
lock_data = read_json(lock_path)
dependencies = manifest.get("dependencies") if isinstance(manifest.get("dependencies"), dict) else {}
lock_dependencies = lock_data.get("dependencies") if isinstance(lock_data.get("dependencies"), dict) else {}
package_lock = lock_dependencies.get("com.xuunity.light-mcp") if isinstance(lock_dependencies.get("com.xuunity.light-mcp"), dict) else {}
test_framework_lock = lock_dependencies.get("com.unity.test-framework") if isinstance(lock_dependencies.get("com.unity.test-framework"), dict) else {}

testables = manifest.get("testables") if isinstance(manifest.get("testables"), list) else []
testables_enabled = "com.xuunity.light-mcp" in testables
source_root = resolve_package_source(manifest, manifest_path, project_root, ops_root)
tests_root = source_root / "Tests"

asmdefs = sorted(tests_root.rglob("*.asmdef")) if tests_root.is_dir() else []
asmdef_names = [asmdef_name(path) for path in asmdefs]
cs_files = sorted(tests_root.rglob("*.cs")) if tests_root.is_dir() else []

category_pattern = re.compile(r'\[Category\s*\(\s*"([^"]+)"\s*\)\s*\]')
test_pattern = re.compile(r"\[(?:Unity)?Test(?:\s*\(|\])")


def assembly_mode(path):
    platforms = read_json(path).get("includePlatforms")
    platforms = platforms if isinstance(platforms, list) else []
    return "editmode" if "Editor" in platforms else "playmode"


def resolved_package_version(name):
    locked = lock_dependencies.get(name)
    if isinstance(locked, dict) and str(locked.get("version") or ""):
        return str(locked.get("version"))
    declared = str(dependencies.get(name) or "")
    return declared if declared[:1].isdigit() else ""


def version_parts(value):
    numbers = []
    for chunk in str(value).split("."):
        digits = ""
        for character in chunk:
            if not character.isdigit():
                break
            digits += character
        numbers.append(int(digits or 0))
    return (numbers + [0, 0, 0])[:3]


def capability_dependencies_installed(path):
    data = read_json(path)
    version_defines = data.get("versionDefines")
    version_defines = version_defines if isinstance(version_defines, list) else []
    for constraint in [str(item) for item in (data.get("defineConstraints") or [])]:
        sources = [entry for entry in version_defines if str((entry or {}).get("define") or "") == constraint]
        if not sources:
            continue
        satisfied = False
        for entry in sources:
            resolved = resolved_package_version(str(entry.get("name") or ""))
            expression = str(entry.get("expression") or "")
            if not resolved:
                continue
            if not expression[:1].isdigit() or version_parts(resolved) >= version_parts(expression):
                satisfied = True
                break
        if not satisfied:
            return False
    return True


assembly_dirs = sorted(
    ((path.parent, asmdef_name(path)) for path in asmdefs),
    key=lambda item: len(item[0].parts),
    reverse=True,
)
assembly_mode_by_name = {asmdef_name(path): assembly_mode(path) for path in asmdefs}


def owning_assembly(cs_path):
    for directory, name in assembly_dirs:
        if directory == cs_path.parent or directory in cs_path.parents:
            return name
    return ""


categories = set()
assembly_categories = {}
editmode_tests = 0
playmode_tests = 0
for cs_path in cs_files:
    text = cs_path.read_text(encoding="utf-8", errors="replace")
    file_categories = category_pattern.findall(text)
    categories.update(file_categories)
    test_count = len(test_pattern.findall(text))
    owner = owning_assembly(cs_path)
    owner_mode = assembly_mode_by_name.get(owner, "")
    if owner_mode == "playmode":
        playmode_tests += test_count
    elif owner_mode == "editmode":
        editmode_tests += test_count
    if test_count > 0 and owner:
        assembly_categories.setdefault(owner, set()).update(file_categories)

required_by_mode = {
    "all": {
        "asmdefs": {"com.xuunity.light-mcp.Editor.Tests", "com.xuunity.light-mcp.PlayMode.Tests"},
        "categories": {"XUUnity.MCP.SelfTest"},
        "editmode_min": 1,
        "playmode_min": 1,
    },
    "editmode": {
        "asmdefs": {"com.xuunity.light-mcp.Editor.Tests"},
        "categories": {"XUUnity.MCP.EditMode"},
        "editmode_min": 1,
        "playmode_min": 0,
    },
    "playmode": {
        "asmdefs": {"com.xuunity.light-mcp.PlayMode.Tests"},
        "categories": {"XUUnity.MCP.PlayMode"},
        "editmode_min": 0,
        "playmode_min": 1,
    },
    "fast": {
        "asmdefs": {"com.xuunity.light-mcp.Editor.Tests", "com.xuunity.light-mcp.PlayMode.Tests"},
        "categories": {"XUUnity.MCP.Fast"},
        "editmode_min": 1,
        "playmode_min": 1,
    },
    "scene": {
        "asmdefs": {"com.xuunity.light-mcp.Editor.Tests", "com.xuunity.light-mcp.PlayMode.Tests"},
        "categories": {"XUUnity.MCP.Scene"},
        "editmode_min": 1,
        "playmode_min": 1,
    },
    "lifecycle": {
        "asmdefs": {"com.xuunity.light-mcp.PlayMode.Tests"},
        "categories": {"XUUnity.MCP.Lifecycle"},
        "editmode_min": 0,
        "playmode_min": 1,
    },
}
required = required_by_mode.get(run_mode, {})
asmdef_name_set = set(asmdef_names)
required_categories = sorted(required.get("categories") or [])

plan_rows = []
for path in asmdefs:
    name = asmdef_name(path)
    contributed = assembly_categories.get(name) or set()
    if not required_categories or not contributed.issuperset(required_categories):
        continue
    if not capability_dependencies_installed(path):
        continue
    plan_rows.append((assembly_mode(path), name, ",".join(required_categories)))
plan_rows.sort()
editmode_plan = [row[1] for row in plan_rows if row[0] == "editmode"]
playmode_plan = [row[1] for row in plan_rows if row[0] == "playmode"]

errors = []
if not testables_enabled:
    errors.append("package_not_in_manifest_testables")
if not dependencies.get("com.unity.test-framework") and not test_framework_lock.get("version"):
    errors.append("unity_test_framework_missing")
if not tests_root.is_dir():
    errors.append("package_tests_directory_missing")
if not asmdefs:
    errors.append("package_test_asmdefs_missing")
for required_asmdef in sorted(required.get("asmdefs") or []):
    if required_asmdef not in asmdef_name_set:
        errors.append(f"missing_asmdef:{required_asmdef}")
for category in sorted(required.get("categories") or []):
    if category not in categories:
        errors.append(f"missing_category:{category}")
if editmode_tests < int(required.get("editmode_min") or 0):
    errors.append("editmode_test_count_zero")
if playmode_tests < int(required.get("playmode_min") or 0):
    errors.append("playmode_test_count_zero")
if int(required.get("editmode_min") or 0) > 0 and not editmode_plan:
    errors.append("editmode_assembly_plan_empty")
if int(required.get("playmode_min") or 0) > 0 and not playmode_plan:
    errors.append("playmode_assembly_plan_empty")

if errors:
    raise SystemExit("package self-test discovery failed: " + ",".join(errors))

with plan_path.open("w", encoding="utf-8", newline="\n") as plan_file:
    for row_mode, row_assembly, row_categories in plan_rows:
        plan_file.write(f"{row_mode}\t{row_assembly}\t{row_categories}\n")

package_source = str(package_lock.get("source") or "manifest")
test_framework_manifest = str(dependencies.get("com.unity.test-framework") or "-")
test_framework_version = str(test_framework_lock.get("version") or "-")
categories_summary = ",".join(sorted(categories)) if categories else "-"
print(
    f"[pass] package-self-test-discovery "
    f"mode={run_mode} "
    f"package_source={package_source} "
    f"package_hash={package_lock.get('hash') or '-'} "
    f"testables=enabled "
    f"test_framework=manifest:{test_framework_manifest}/lock:{test_framework_version} "
    f"asmdefs={len(asmdefs)} "
    f"editmode_tests={editmode_tests} "
    f"playmode_tests={playmode_tests} "
    f"editmode_plan={','.join(editmode_plan) or '-'} "
    f"playmode_plan={','.join(playmode_plan) or '-'} "
    f"categories={categories_summary} "
    f"source_root={source_root}"
)
PY
}

ensure_ready_cmd=(
  "$WRAPPER" ensure-ready
  --project-root "$PROJECT_ROOT"
  --timeout-ms 180000
)
if [[ "$OPEN_EDITOR" == "true" ]]; then
  ensure_ready_cmd+=(--open-editor)
fi
if (( ${#UNITY_ARGS[@]} > 0 )); then
  for unity_arg in "${UNITY_ARGS[@]}"; do
    ensure_ready_cmd+=("--unity-arg=$unity_arg")
  done
fi

"${ensure_ready_cmd[@]}" >/dev/null
PATCH_RESULT="$(enable_package_tests)"
if [[ "$PATCH_RESULT" == "patched" ]]; then
  MANIFEST_WAS_PATCHED="true"
fi
"$WRAPPER" request-project-refresh --project-root "$PROJECT_ROOT" --timeout-ms 180000 >/dev/null
print_package_self_test_discovery

run_mcp_json_step() {
  local label="$1"
  local assembly="$2"
  shift 2
  local output_path="$TMP_DIR/${label}.json"
  if ! "$@" >"$output_path"; then
    cat "$output_path"
    return 1
  fi
  cat "$output_path"
  python3 - "$output_path" "$label" "$assembly" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
label = sys.argv[2]
assembly = sys.argv[3]
payload = json.loads(path.read_text(encoding="utf-8"))
status = str(payload.get("status") or "")
if status not in {"ok", "success"}:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = error.get("code") or "mcp_response_error"
    message = error.get("message") or f"{label} returned status {status}"
    print(f"{label} failed: {code}: {message}", file=sys.stderr)
    raise SystemExit(1)

test_payload = payload
if isinstance(payload.get("payload_json"), str) and payload.get("payload_json"):
    try:
        test_payload = json.loads(payload["payload_json"])
    except json.JSONDecodeError as exc:
        print(f"{label} failed: test payload JSON could not be decoded: {exc}", file=sys.stderr)
        raise SystemExit(1)

test_status = str(test_payload.get("status") or "")
total = int(test_payload.get("total") or test_payload.get("test_count") or 0)
passed = int(test_payload.get("passed") or 0)
failed = int(test_payload.get("failed") or 0)
skipped = int(test_payload.get("skipped") or 0)

if test_status == "no_tests" or total <= 0:
    print(
        f"{label} failed: package_self_tests_assembly_contributed_no_tests: "
        f"assembly={assembly} contributed 0 tests. That assembly ships in the package and its "
        f"capability dependencies are installed in this project, so either the run filter or the "
        f"test categories regressed. Compare the assembly against the editmode_plan/playmode_plan "
        f"printed by package-self-test-discovery.",
        file=sys.stderr,
    )
    raise SystemExit(1)

if failed > 0 or test_status not in {"passed", "ok", "success"}:
    print(
        f"{label} failed: package_self_tests_failed: "
        f"status={test_status} total={total} passed={passed} failed={failed} skipped={skipped}",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(
    f"[pass] package-self-tests label={label} "
    f"status={test_status} total={total} passed={passed} failed={failed} skipped={skipped}"
)
PY
}

load_planned_assemblies() {
  local wanted_mode="$1"
  local row_mode=""
  local row_assembly=""
  PLANNED_ASSEMBLIES=()
  while IFS=$'\t' read -r row_mode row_assembly _; do
    if [[ "$row_mode" == "$wanted_mode" ]]; then
      PLANNED_ASSEMBLIES+=("$row_assembly")
    fi
  done < "$ASSEMBLY_PLAN_PATH"
  if (( ${#PLANNED_ASSEMBLIES[@]} == 0 )); then
    echo "package self-test $wanted_mode assembly plan is empty for mode=$RUN_MODE" >&2
    return 1
  fi
}

run_editmode() {
  local category="$1"
  local assembly=""
  load_planned_assemblies editmode
  for assembly in "${PLANNED_ASSEMBLIES[@]}"; do
    run_mcp_json_step "editmode_${assembly//[^A-Za-z0-9_]/_}_${category//[^A-Za-z0-9_]/_}" "$assembly" \
      "$WRAPPER" request-editmode-tests \
      --project-root "$PROJECT_ROOT" \
      --assembly-name "$assembly" \
      --category-name "$category" \
      --timeout-ms "$TIMEOUT_MS"
  done
}

run_playmode() {
  local category="$1"
  local assembly=""
  load_planned_assemblies playmode
  for assembly in "${PLANNED_ASSEMBLIES[@]}"; do
    run_mcp_json_step "playmode_${assembly//[^A-Za-z0-9_]/_}_${category//[^A-Za-z0-9_]/_}" "$assembly" \
      "$WRAPPER" request-playmode-tests \
      --project-root "$PROJECT_ROOT" \
      --assembly-name "$assembly" \
      --category-name "$category" \
      --timeout-ms "$TIMEOUT_MS"
  done
}

case "$RUN_MODE" in
  all)
    run_editmode XUUnity.MCP.SelfTest
    run_playmode XUUnity.MCP.SelfTest
    ;;
  editmode)
    run_editmode XUUnity.MCP.EditMode
    ;;
  playmode)
    run_playmode XUUnity.MCP.PlayMode
    ;;
  fast)
    run_editmode XUUnity.MCP.Fast
    run_playmode XUUnity.MCP.Fast
    ;;
  scene)
    run_editmode XUUnity.MCP.Scene
    run_playmode XUUnity.MCP.Scene
    ;;
  lifecycle)
    run_playmode XUUnity.MCP.Lifecycle
    ;;
  *)
    fail_usage "Unsupported --mode: $RUN_MODE"
    ;;
esac
