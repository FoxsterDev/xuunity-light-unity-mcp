# Project Action Templates

These templates are public-safe starting points for project-owned MCP actions.
Copy the relevant fragment into the consumer project's `project_actions.yaml`
and place the C# hook in a project Editor assembly that references
`XUUnity.LightMcp.Editor.ScenarioHooks`.

`config_applying_build.project_actions.yaml` and
`ConfigApplyingBuildActionHook.cs.template` show a config-applying build lane.
The project fills in its own menu path or zero-argument static build method so
the MCP action drives the same configured build path that humans use. This is
for projects where raw `unity_build_player` or `batch-build-player` would skip
profile application, signing setup, dependency generation, or other project
build-tool behavior.

Catalog actions whose defaults only make sense in the owning host may declare
`hostScoped: true` plus `requiredPayloadFields`. Invocation then fails with
`hook_is_host_scoped` until every project-specific field is supplied; it never
silently inherits the hook owner's path.

Profile/config actions that trigger a domain reload may declare
`settlePolicy: apply_then_gate`. A direct project-action invocation then builds
the safe `apply -> wait -> status -> compile_player_scripts` sequence and
requires `build_target` or `target`. When such an action is embedded in a
larger scenario, the author must place those three gate steps immediately after
it; `project_refresh` is rejected in that position.

Every typed action now passes through `project_action_currency` before its hook.
The gate compares the loaded editor-domain timestamp with the newest editor
input under `Assets` and fails closed when it is stale or unknown. An action
that reads assets which may have changed outside Unity should also declare
`requiresFreshAssets: true`; invocation then automatically runs a forced
AssetDatabase refresh without package resolution or an extra health probe,
waits for settle/domain reload, re-checks currency, and invokes the hook only
when both preconditions pass.

```yaml
  project.apply_profile:
    hookName: example.project_environment
    settlePolicy: apply_then_gate
    payload:
      build_target: enum[Android, iOS]
  project.switch_host_target:
    hookName: example.host_build
    hostScoped: true
    requiresFreshAssets: true
    requiredPayloadFields: [config_resource_path]
    payload:
      config_resource_path: project-specific resource path
      build_target: enum[Android, iOS]
```
