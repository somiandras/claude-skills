# claude-skills

Personal Claude Code marketplace. Each plugin lives under `plugins/<name>/`
with a `.claude-plugin/plugin.json` manifest. The marketplace manifest at
`.claude-plugin/marketplace.json` lists every plugin and its version.

## Hard rule: bump version on every update

**Every change to a plugin's content MUST bump the version.** No exceptions.

Without a version bump, the plugin manager has no signal to refresh the
local cache. Users running `/plugin update` will see "already up to date"
even though the canonical source has changed, and the only way to apply
the change becomes hand-editing the cache — which is unreliable and gets
overwritten on the next legitimate update.

**Two files must be edited together:**

1. `plugins/<name>/.claude-plugin/plugin.json` — bump `version`
2. `.claude-plugin/marketplace.json` — bump the matching `version` entry

Both versions must agree. Use semver: patch for fixes/wording, minor for
new features, major for breaking changes.

After pushing, the user runs `/plugin update <name>@somiandras-skills`
in Claude Code to repopulate the cache.

## Never edit the cache directly

Do **not** patch files under `~/.claude/plugins/cache/somiandras-skills/`
as a substitute for a real release. The cache is a derived artifact —
hand edits survive only until the next plugin manager refresh. Always
fix the source in this repo, bump the version, push, and update.
