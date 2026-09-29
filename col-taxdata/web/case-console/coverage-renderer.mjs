function makeNode(document, tag, className = null, text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null && text !== undefined) node.textContent = String(text);
  return node;
}

function humanize(value) {
  if (value === null || value === undefined || value === "") return "Not provided";
  return String(value).replaceAll("_", " ");
}

function titleCase(value) {
  const text = humanize(value);
  return text === "Not provided"
    ? text
    : text.charAt(0).toUpperCase() + text.slice(1);
}

export function safeHttpUrl(value) {
  if (typeof value !== "string" || value.length === 0) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return parsed.href;
  } catch {
    return null;
  }
}

function appendChip(document, parent, label, value, kind = "neutral") {
  const chip = makeNode(document, "span", `coverage-chip coverage-chip-${kind}`);
  chip.setAttribute("data-coverage-kind", kind);
  chip.textContent = `${label}: ${humanize(value)}`;
  parent.append(chip);
}

function appendDefinition(document, parent, label, value) {
  const row = makeNode(document, "div", "coverage-definition");
  const key = makeNode(document, "span", "coverage-definition-key", `${label}:`);
  const content = makeNode(
    document,
    "span",
    "coverage-definition-value",
    humanize(value),
  );
  row.append(key, content);
  parent.append(row);
}

function temporalSelectionLabel(status) {
  const labels = {
    effective_as_of: "Effective as of caller date",
    historical_as_of: "Historical as of caller date",
    not_effective_as_of: "Not effective as of caller date",
    ambiguous: "Temporal applicability ambiguous",
    unassessed: "Temporal applicability unassessed",
  };
  return labels[status] ?? `Temporal state: ${humanize(status)}`;
}

function renderWarnings(document, aspectNode, warnings) {
  if (!Array.isArray(warnings) || warnings.length === 0) return;
  const heading = makeNode(document, "h5", "coverage-subheading", "Limitations");
  aspectNode.append(heading);

  const list = makeNode(document, "ul", "warning-list");
  for (const warning of warnings) {
    const item = makeNode(
      document,
      "li",
      `coverage-warning coverage-warning-${warning.kind ?? "other"}`,
    );
    item.setAttribute("data-warning-code", warning.code ?? "unknown");
    const strong = makeNode(
      document,
      "strong",
      null,
      warning.label ?? "Research limitation",
    );
    item.append(strong);
    if (warning.detail) {
      item.append(makeNode(document, "span", null, ` — ${warning.detail}`));
    }
    list.append(item);
  }
  aspectNode.append(list);
}

function renderEvidence(document, aspectNode, evidenceItems) {
  const heading = makeNode(document, "h5", "coverage-subheading", "Selected exact evidence");
  aspectNode.append(heading);

  if (!Array.isArray(evidenceItems) || evidenceItems.length === 0) {
    aspectNode.append(
      makeNode(
        document,
        "p",
        "empty coverage-empty",
        "No exact evidence is selected for this aspect.",
      ),
    );
    return;
  }

  const evidenceList = makeNode(document, "div", "evidence-list");
  for (const evidence of evidenceItems) {
    const card = makeNode(document, "article", "evidence-card");
    const quote = makeNode(
      document,
      "blockquote",
      "evidence-exact-text",
      evidence.exact_text ?? "Exact evidence text is unavailable.",
    );
    card.append(quote);

    const meta = makeNode(document, "div", "evidence-meta");
    appendDefinition(
      document,
      meta,
      "Authority",
      evidence.authority?.display_name ?? evidence.authority?.authority_ref,
    );
    appendDefinition(document, meta, "Document type", evidence.authority?.document_type);
    appendDefinition(document, meta, "Issuer", evidence.authority?.issuer);
    appendDefinition(
      document,
      meta,
      "Classification",
      evidence.authority?.classification_state,
    );
    appendDefinition(document, meta, "Document", evidence.document_ref);
    appendDefinition(document, meta, "Provision", evidence.provision_ref);
    appendDefinition(document, meta, "Selection basis", evidence.basis);
    appendDefinition(document, meta, "Context", evidence.context_status);
    appendDefinition(
      document,
      meta,
      "Temporal evidence",
      temporalSelectionLabel(evidence.temporal_status),
    );
    card.append(meta);

    if (
      evidence.authority?.classification_state === "ambiguous" ||
      evidence.authority?.classification_state === "partial" ||
      evidence.authority?.classification_state === "unknown" ||
      !evidence.authority?.issuer ||
      !evidence.authority?.document_type
    ) {
      card.append(
        makeNode(
          document,
          "p",
          "authority-metadata-warning",
          "Authority metadata ambiguous or incomplete; the console does not guess missing fields.",
        ),
      );
    }

    const sourceUri = safeHttpUrl(evidence.source?.source_uri);
    if (sourceUri) {
      const link = makeNode(
        document,
        "a",
        "official-source-link",
        evidence.source?.title
          ? `Official source: ${evidence.source.title}`
          : "Open official source",
      );
      link.href = sourceUri;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
    } else {
      card.append(
        makeNode(
          document,
          "p",
          "source-unavailable",
          "Official source link unavailable.",
        ),
      );
    }

    evidenceList.append(card);
  }
  aspectNode.append(evidenceList);
}

function renderAspect(document, aspect) {
  const node = makeNode(document, "article", "aspect-card");
  node.setAttribute("data-aspect-ref", aspect.aspect_ref ?? "");

  const headingRow = makeNode(document, "div", "aspect-heading");
  const heading = makeNode(
    document,
    "h4",
    null,
    aspect.dimension_key ?? aspect.aspect_ref ?? "Research aspect",
  );
  headingRow.append(heading);
  if (aspect.required === true) {
    headingRow.append(makeNode(document, "span", "required-marker", "required"));
  }
  node.append(headingRow);

  if (aspect.research_goal) {
    node.append(makeNode(document, "p", "research-goal", aspect.research_goal));
  }

  const chips = makeNode(document, "div", "coverage-chips");
  appendChip(document, chips, "Scope", aspect.scope_status);
  appendChip(document, chips, "Origin", aspect.origin);
  if (aspect.coverage) {
    appendChip(
      document,
      chips,
      "Execution",
      aspect.coverage.execution_status,
      aspect.coverage.execution_status === "complete" ? "good" : "attention",
    );
    appendChip(
      document,
      chips,
      "Evidence",
      aspect.coverage.evidence_status,
      aspect.coverage.evidence_status === "context_ready" ? "good" : "attention",
    );
    appendChip(
      document,
      chips,
      "Authority",
      aspect.coverage.authority_status,
      aspect.coverage.authority_status === "resolved" ? "good" : "attention",
    );
    appendChip(
      document,
      chips,
      "Temporal",
      aspect.coverage.temporal_status,
      aspect.coverage.temporal_status === "assessed" ? "good" : "attention",
    );
    appendChip(
      document,
      chips,
      "Facts",
      aspect.coverage.fact_status,
      ["not_required", "sufficient"].includes(aspect.coverage.fact_status)
        ? "good"
        : "attention",
    );
    appendChip(
      document,
      chips,
      "Support closure",
      aspect.coverage.support_closure,
      aspect.coverage.support_closure === "complete" ? "good" : "attention",
    );
  }
  node.append(chips);

  if (aspect.external_synthesis) {
    node.append(
      makeNode(
        document,
        "p",
        "synthesis-note",
        "Interpretive synthesis remains external to col-taxdata for this aspect; research coverage is not a legal conclusion.",
      ),
    );
  }

  renderWarnings(document, node, aspect.warnings);
  renderEvidence(document, node, aspect.selected_evidence);
  return node;
}

export function renderCoverage(document, panel, coverage) {
  panel.replaceChildren();

  if (!coverage) {
    panel.append(
      makeNode(
        document,
        "p",
        "empty",
        "No coverage view is available for this response.",
      ),
    );
    return;
  }

  if (!coverage.available) {
    const message = makeNode(document, "section", "coverage-version-message");
    message.append(
      makeNode(
        document,
        "h3",
        null,
        coverage.compatibility === "unsupported"
          ? "Unsupported response version"
          : "Coverage view unavailable for this historical contract",
      ),
    );
    message.append(
      makeNode(
        document,
        "p",
        null,
        coverage.version_message ?? "No structured coverage is available.",
      ),
    );
    panel.append(message);
    return;
  }

  const summary = makeNode(document, "section", "coverage-summary");
  const chips = makeNode(document, "div", "coverage-chips");
  appendChip(
    document,
    chips,
    "Bundle",
    coverage.bundle_status,
    coverage.bundle_status === "complete" ? "good" : "attention",
  );
  appendChip(
    document,
    chips,
    "Research",
    coverage.research_status,
    coverage.research_status === "complete" ? "good" : "attention",
  );
  summary.append(chips);

  summary.append(
    makeNode(
      document,
      "p",
      "date-policy-note",
      coverage.as_of_date
        ? `Temporal input: ${coverage.as_of_date} (caller supplied).`
        : "No as_of_date was submitted. Temporal applicability remains unassessed; no browser or server clock value was inserted.",
    ),
  );
  summary.append(
    makeNode(
      document,
      "p",
      "coverage-boundary-note",
      "Research coverage describes executed work and evidence support. It does not itself state a legal conclusion.",
    ),
  );
  panel.append(summary);

  if (!Array.isArray(coverage.questions) || coverage.questions.length === 0) {
    panel.append(
      makeNode(
        document,
        "p",
        "empty",
        "No public question/aspect coverage is available.",
      ),
    );
    return;
  }

  for (const question of coverage.questions) {
    const questionNode = makeNode(document, "section", "question-card");
    questionNode.setAttribute("data-question-ref", question.question_ref ?? "");
    questionNode.append(
      makeNode(
        document,
        "h3",
        null,
        question.text ?? question.question_ref ?? "Question",
      ),
    );
    const meta = makeNode(document, "div", "question-meta");
    appendDefinition(document, meta, "Question ref", question.question_ref);
    appendDefinition(document, meta, "Category", question.category);
    appendDefinition(document, meta, "Question state", question.status);
    questionNode.append(meta);

    if (!Array.isArray(question.aspects) || question.aspects.length === 0) {
      questionNode.append(
        makeNode(document, "p", "empty", "No research aspects were planned."),
      );
    } else {
      for (const aspect of question.aspects) {
        questionNode.append(renderAspect(document, aspect));
      }
    }

    panel.append(questionNode);
  }
}
