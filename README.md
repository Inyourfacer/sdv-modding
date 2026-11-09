# sdv-modding

Stardew Valley 1.6 mods, plus the `sdv-modding` Claude Code skill in `.claude/skills/sdv-modding/`.

Any Claude Code session opened on this repo (desktop, web or phone) loads the skill automatically. Ask for a Stardew modding task, or type `/sdv-modding`.

## Layout
- `.claude/skills/sdv-modding/` — the skill: instructions, framework references, asset specs, scripts
- `mods/` — your mods (create folders here, e.g. `mods/[CP] My Mod/`)
- `sdv-modding.config.json` — your settings; copy from `.claude/skills/sdv-modding/config.example.json`

## Local use (Windows)
Clone this repo and run `claude` inside it, or copy `.claude/skills/sdv-modding` to `%USERPROFILE%\.claude\skills\` to use it in every project. Scripts need `pip install pillow numpy`.
