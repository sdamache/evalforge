# Phase 0 Research: Documentation + Devpost Submission

This feature is documentation-focused. The research phase records decisions about where docs live, how diagrams/contracts are represented, and how submission assets map to repository sources.

## Decisions

### Decision: Keep `README.md` as the single entry point

**Rationale**
- Hackathon judges and new contributors default to the repo root; a complete README reduces friction.
- Deeper implementation details already live under `specs/` and `docs/`; README should link to those sources rather than duplicate them.

**Alternatives considered**
- Split docs across multiple top-level markdown files (rejected: increases discovery overhead and risks drift).
- Rely entirely on `docs/` (rejected: judges often never click into subfolders).

---

### Decision: Use Mermaid as the architecture diagram source of truth

**Rationale**
- Mermaid diagrams are text-based, versionable, and render in GitHub and many markdown environments.
- A single Mermaid diagram can be embedded in both README and Devpost (as an image export if needed).

**Alternatives considered**
- draw.io only (rejected: binary diffs and more merge conflicts).
- ASCII-only diagrams (rejected: harder to maintain and less visually legible in Devpost).

---

### Decision: Treat `specs/*/contracts/*.yaml` as canonical API references

**Rationale**
- The repository already maintains service-level OpenAPI contracts under each feature spec.
- Reusing these avoids inventing new “documentation contracts” that can drift from implementation.

**Alternatives considered**
- Auto-generate OpenAPI from FastAPI at build time (rejected: adds tooling/setup risk for hackathon and can change formatting unexpectedly).
- Handwritten API reference in README only (rejected: duplication; schema-level detail belongs in OpenAPI).

---

### Decision: Submission assets are produced manually, with a repo-backed checklist

**Rationale**
- Screenshots and videos are inherently manual, but the team can standardize *what* to capture and *in what order* using a simple checklist and timing guidance.
- Keeping a simple checklist in-repo reduces “who remembers the steps?” churn right before submission.

**Alternatives considered**
- Fully automated screenshot capture (rejected: environment-specific, requires UI harnesses not present in this repo).

---

### Decision: Demo story focuses on the end-to-end “incident → insight → approval” loop

**Rationale**
- The project’s differentiator is the feedback loop from real production traces to actionable outputs.
- A 3-minute demo should emphasize the loop and evidence trail, not deep code walkthroughs.

**Alternatives considered**
- Deep technical walkthrough of each service (rejected: too slow for 3 minutes and loses the narrative).
