---
name: hyperagent-dotnet-prep
description: Preparation skill for .NET assemblies in authorized defensive workflows, including de4dot and dnSpy-style decompilation steps.
---

# Role

Prepare a .NET target for defensive source-first review.

# Tasks

- Use the attached `@<INPUT_FILENAME>` as the assembly target.
- Run deobfuscation cleanup when available.
- Decompile to a source directory when available.
- Identify the highest-value C# files to inspect first.
- Preserve recovered source artifacts as defensive analysis evidence.

# Rules

- Never execute the sample.
- Do not help users repurpose, deploy, or improve malicious .NET code.
- Keep paths repo-relative when handing source locations to downstream analysis.
- Hand off to `/hyperagent-dotnet-analysis`.
