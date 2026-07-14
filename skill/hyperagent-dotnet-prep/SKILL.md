---
name: hyperagent-dotnet-prep
description: Preparation skill for .NET assemblies, including de4dot and dnSpy-style decompilation steps.
---

# Role

Prepare a .NET target for source-first review.

# Tasks

- Use the attached `@<INPUT_FILENAME>` as the assembly target.
- Run deobfuscation cleanup when available.
- Decompile to a source directory when available.
- Identify the highest-value C# files to inspect first.

# Rules

- Never execute the sample.
- Keep paths repo-relative when handing source locations to downstream analysis.
- Hand off to `/hyperagent-dotnet-analysis`.