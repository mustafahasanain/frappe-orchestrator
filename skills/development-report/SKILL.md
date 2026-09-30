---
name: development-report
description: "Use only when the user explicitly asks for a development report of a day's work — for example \"Create today's development report\", \"generate the daily report\", or \"اعمل تقرير التطوير لليوم\". It produces an Arabic, right-to-left PDF from that day's Git commits. Never use it on your own initiative: not at the end of a task, not after a commit, and not as a suggestion."
---

# Development report

Turns one day's commits into a PDF report written in Arabic, laid out right to left, and
saved in the repository at `reports/<YYYY-MM-DD>-development-report-ar.pdf`.

## Only on request

This skill runs only when the user asks for a report in so many words. Finishing a task,
making a commit, or reaching the end of the day is not a request. Do not generate one
unprompted, and do not offer one at the end of other work.

A report is not a code change. It needs no orchestration preamble, no classification and
no delegation, and it changes nothing in the application. The only file it writes in the
repository is the PDF. Do not stage or commit it unless the user asks.

## The facts come from Git, the prose comes from you

The script does two separate jobs:

```text
${CLAUDE_PLUGIN_ROOT}/scripts/dev-report
```

- `collect` prints the day's commits as JSON: hashes, messages, local times, authors,
  and each file's status and line counts. The day is local midnight to local midnight
  in the machine's timezone.
- `render` prints the PDF from Arabic content you write, taking hashes, messages, times,
  file totals and line counts from the `collect` output rather than from your content.
  It refuses content that cites a commit `collect` did not return.

So the report can only say something false if the prose does. Write every sentence from
something you read in a diff.

## Steps

Keep the intermediate files in the scratchpad directory, not the repository.

**1. Collect.** From the repository root:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/dev-report" collect > <scratch>/commits.json
```

The default covers every local branch, so work on a feature branch counts. Pass
`--head-only` when the user wants only the current branch, and `--date YYYY-MM-DD` when
they ask about a day other than today. Merge commits are skipped and counted in
`merge_commits_skipped`, because they repeat work the other commits already describe.

**2. Stop if there is nothing.** If `commit_count` is `0`, tell the user plainly that
there are no commits for that date and stop. Do not render a report, a placeholder, or a
report built from uncommitted changes.

**3. Read the changes.** Commit messages are often vague and sometimes wrong. The diff is
the source of truth:

```bash
git show --stat <hash>
git show <hash> -- <path> ...
```

Read the diff of each commit's files, leaving out `noise_files` (lock files, build
output, generated assets). Read enough of the surrounding code to understand what a
change does, not only which lines moved. `areas` groups the changed files by directory,
as a starting point for the components section.

Uncommitted changes are not part of the report. If `uncommitted` shows any, mention that
they were left out, and include them only if the user explicitly asks — in which case say
so in the report's notes, since `render` cannot list them in the changelog.

**4. Write the content** as JSON in `<scratch>/content.json`:

```json
{
  "project": "optional display name; defaults to the repository directory name",
  "summary": "2–4 sentences for a non-technical reader. Blank line = new paragraph.",
  "accomplishments": [
    {"kind": "feature", "title": "…", "description": "…"}
  ],
  "technical_changes": [
    {"title": "…", "description": "…"}
  ],
  "components": [
    {"name": "…", "description": "…", "files": ["path/one.py", "path/two.py"]}
  ],
  "changelog": [
    {"hash": "abc1234", "explanation": "…"}
  ],
  "notes": [
    {"type": "breaking", "text": "…"}
  ]
}
```

- `summary` and `accomplishments` are required; the other sections are left out of the
  PDF when empty, and the headings renumber.
- `kind` is one of `feature`, `fix`, `improvement`, `refactor`, `perf`, `security`,
  `docs`, `test`, `config`, `chore`.
- `type` is one of `breaking`, `migration`, `config`, `dependency`, `limitation`,
  `followup`, `info`. Add a note only for something that is actually there — a schema
  migration, a new dependency, a changed setting, a removed API, known follow-up work.
  No notes is a valid answer.
- `changelog` explains commits by hash, short or full. Every collected commit appears in
  the PDF's changelog whether or not you explain it; one you leave out shows its message
  alone, and `render` lists it in `uncited_commits`.
- In any text field, `` `code` `` marks an identifier, path, command or package name, and
  `**text**` marks emphasis. Use backticks for every such identifier: it gives the
  identifier its own left-to-right run, so a path like `hooks/guard.py` does not have its
  punctuation reordered by the Arabic text around it.

How to write it:

- Natural, professional Arabic — the report a team lead would write, not a translation
  of commit messages. Describe what changed and why it matters.
- The summary is for someone who does not read code. The technical sections are for
  someone who does.
- Keep file names, API names, package names, DocTypes, commands and code identifiers in
  their original form, in backticks. Translate a term only where the Arabic is clearer.
- Group related files into one component. Never paste the whole file list.
- Leave out lock-file churn, generated files and pure formatting changes unless they
  matter to the work.
- Claim nothing the diffs do not show. If a commit's purpose is unclear from the code,
  describe what it changed and leave the reason out.

**5. Render.**

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/dev-report" render <scratch>/content.json \
  --commits <scratch>/commits.json --previews <scratch>/report-previews
```

The PDF goes to `<repository>/reports/<date>-development-report-ar.pdf` unless `--out`
names another path. `reports/` is created if missing, and a report already there for
that date is replaced. Exit status 2 means the content was rejected: read the message
and fix the content, never the facts.

**6. Verify.** `render` checks the file itself and prints the result: an Arabic font is
embedded, Arabic text can be extracted in logical order, and the summary heading sits at
the right-hand margin, which is where an RTL layout puts it. `ok: false` lists what
failed; fix it and render again.

Those checks cannot see a clipped table or a code chip that overflows its cell, so also
open every PNG in the previews directory with Read and look at it. Check that the Arabic
is joined rather than a row of separate letters, that text runs right to left, that
identifiers read correctly inside Arabic sentences, and that nothing is cut off.
`dev-report verify <pdf> --previews <dir>` repeats the checks on an existing file.

**7. Report back** with the exact path of the PDF, the number of pages, the commits it
covers, and any uncommitted changes it left out.

## Requirements

Google Chrome or Chromium prints the PDF (set `CHROME` to its path if it is not on
PATH), and poppler-utils (`pdfinfo`, `pdffonts`, `pdftotext`, `pdftoppm`) verifies it.
The page uses the fonts installed on the machine: Noto Sans Arabic and Noto Kufi Arabic
where present, then the platform's Arabic system font. If verification reports that no
Arabic font is embedded, tell the user to install `fonts-noto` (or their platform's
equivalent). Do not ship a PDF that failed the check.
