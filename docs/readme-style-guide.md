# Public README style guide

Use the current root `README.md` as the structural reference for future public README updates.

## Structure

Keep the sections in this order unless the product changes enough to justify a different flow:

1. **Product name and value proposition:** a short headline describing the user's benefit, followed by a concise paragraph that explains the product and its daily workflow.
2. **Release status:** state clearly whether the build is preview, beta, or stable, and call out key distribution constraints early.
3. **Useful features:** concise bullets focused on outcomes and practical capabilities, including the defining feature (currently Sticky Code).
4. **Details that matter:** explain behaviors that affect everyday use, such as hide versus delete, resizing, scrolling, and whether code is executed.
5. **Install the Linux release:** explain compatibility first, then give numbered download/install/run steps, checksum verification, update behavior, and any runtime prompt.
6. **Privacy and storage:** state where data is stored and what the PIN does and does not protect; explain attachment and email behavior plainly.
7. **Compatibility and current limits:** distinguish tested combinations from unverified ones and avoid universal Linux compatibility claims.
8. **Keyboard shortcuts:** use a compact Shortcut / Action table and mention any in-app shortcut reference.
9. **Build from source:** list prerequisites, reproducible commands, native development requirements, and the test command.
10. **Project and community:** state ownership/license and provide source, issue, and release links with a welcoming but direct call to action.

## Voice and accuracy

- Write the public README in English for Linux desktop users and open-source contributors.
- Lead with useful user outcomes, daily tasks, and workflow. Use words such as “useful,” “great features,” “awesome,” “productive,” and “details that matter” naturally; avoid keyword stuffing or exaggerated promises.
- Keep paragraphs short, headings descriptive, installation commands copyable, and lists focused on decisions users need to make.
- Pair an appealing product presentation with specific, honest information about release maturity, supported architectures, desktop/runtime requirements, privacy, and known limitations.
- Do not claim a feature or platform is tested unless the validation records support that claim. Put detailed test evidence, audit findings, and engineering history in `docs/`, not in the product pitch.
- Do not include internal agent/Codex context, private user information, or unsupported security claims in the public README.
- Recheck links, package names, versions, commands, and product claims whenever the README changes.
