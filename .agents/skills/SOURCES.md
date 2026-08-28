# Project-local skill sources

Validated 2026-08-28. These packages support Codex development and testing only; they are not Floodman runtime dependencies and are excluded from Pterodactyl packaging.

| Skill | Source repository | Source subdirectory | Source commit | Local path | License | State and validation |
|---|---|---|---|---|---|---|
| Frontend Design Pro | `Krishna-Modi12/frontend-design-pro` | `/` | `09f294c78cce28c90445f385546b2f2c49b8d831` | `.agents/skills/frontend-design-pro/` | MIT; bundled `LICENSE` | Newly installed with the full root registry, routed skills, core references, validators, and scripts. Upstream reference checker: 144 files, 0 violations. Its JSONC-style screenshot `tsconfig.json` was normalized to equivalent strict JSON for the Floodman repository validator. |
| Playwright CLI | `microsoft/playwright-cli` | `skills/playwright-cli/` | `cbc09311c468e10fba47964e9b3830fe625c9b01` | `.agents/skills/playwright-cli/` | Apache-2.0; bundled as `UPSTREAM-LICENSE.txt` | Newly installed; `SKILL.md` plus all eight referenced instruction files are present and relative links resolve. |
| UI/UX Pro Max | `nextlevelbuilder/ui-ux-pro-max-skill` | `.claude/skills/ui-ux-pro-max/` | `8bd29e775453ebcae52b6e6514fbf134df0c5770` | `.agents/skills/ui-ux-pro-max/` | MIT; bundled as `UPSTREAM-LICENSE.txt` | Newly installed with data, references, search scripts, and tests. Validator passed 12 domain files, 22 stack files, and `ui-reasoning.csv`. |
| Anti-AI-Slop UI/UX | `Vanszs/Anti-AI-UI` | `Anti-AI-SLop/` | `fd2a142e52e0f33002bb3c9cf966f0e878d31dfa` | `.agents/skills/anti-ai-slop/` | MIT; bundled as `UPSTREAM-LICENSE.txt` | Newly installed; `SKILL.md` and both required references are present and resolve. |
| Playwright Best Practices | `currents-dev/playwright-best-practices-skill` | `playwright-best-practices/` | `283d5cbc5d11aac1abda058b16ad22c317d54dc0` | `.agents/skills/playwright-best-practices/` | MIT; bundled as `UPSTREAM-LICENSE.txt` | Newly installed with all reference families. Seven cross-directory Markdown links were corrected locally; the complete relative-link audit passes. |

Validation also confirmed 24 unique routed skill names and no nested `.git`, `node_modules`, virtual environment, cache, distribution, or build directory under `.agents/skills/`. Upstream trailing whitespace was mechanically normalized in the 24 files flagged by Floodman's staged-diff policy; this did not change the validators' results.
