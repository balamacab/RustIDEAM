export const TOP_LEVEL_SUCCESS_FIELDS = Object.freeze([
  "api_version",
  "request_fingerprints",
  "bundle",
]);

export const VIEW_BUNDLE_FIELDS = Object.freeze({
  result: Object.freeze([
    "kind",
    "contract_version",
    "bundle_ref",
    "status",
    "generated_at",
    "case_input",
  ]),
  intake: Object.freeze(["case_input", "intake_draft"]),
  research: Object.freeze(["research_plan", "research_result"]),
  evidence: Object.freeze([
    "sources",
    "authorities",
    "evidence_spans",
    "normative_relationships",
    "rule_fragments",
  ]),
  evaluations: Object.freeze([
    "deterministic_evaluations",
    "calculation_traces",
  ]),
  unresolved: Object.freeze(["unresolved"]),
});

function pickOwn(source, fields) {
  const selected = {};
  for (const field of fields) {
    if (Object.prototype.hasOwnProperty.call(source, field)) {
      selected[field] = source[field];
    }
  }
  return selected;
}

export function buildRequest(problemText, asOfDate, clientReference, callerMetadataText) {
  if (problemText.length === 0) {
    throw new Error("problem_text is required.");
  }

  const request = { problem_text: problemText };
  if (asOfDate.length > 0) request.as_of_date = asOfDate;
  if (clientReference.length > 0) request.client_reference = clientReference;

  if (callerMetadataText.length > 0) {
    let metadata;
    try {
      metadata = JSON.parse(callerMetadataText);
    } catch {
      throw new Error("caller_metadata must be valid JSON.");
    }
    if (metadata === null || Array.isArray(metadata) || typeof metadata !== "object") {
      throw new Error("caller_metadata must be a JSON object.");
    }
    request.caller_metadata = metadata;
  }
  return request;
}

export function buildViewModels(payload) {
  if (payload === null || Array.isArray(payload) || typeof payload !== "object") {
    throw new Error("CASE response is not a JSON object.");
  }

  if (Object.prototype.hasOwnProperty.call(payload, "error")) {
    const diagnostics = {};
    if (Object.prototype.hasOwnProperty.call(payload, "api_version")) {
      diagnostics.api_version = payload.api_version;
    }
    if (Object.prototype.hasOwnProperty.call(payload, "request_fingerprints")) {
      diagnostics.request_fingerprints = payload.request_fingerprints;
    }
    return {
      result: { error: payload.error },
      intake: null,
      research: null,
      evidence: null,
      evaluations: null,
      unresolved: null,
      diagnostics,
      raw: payload,
    };
  }

  for (const field of TOP_LEVEL_SUCCESS_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(payload, field)) {
      throw new Error("CASE response does not match the published success envelope.");
    }
  }

  const bundle = payload.bundle;
  if (bundle === null || Array.isArray(bundle) || typeof bundle !== "object") {
    throw new Error("CASE response bundle is not an object.");
  }

  const diagnostics = {
    api_version: payload.api_version,
    request_fingerprints: payload.request_fingerprints,
  };
  if (
    bundle.intake_draft &&
    typeof bundle.intake_draft === "object" &&
    Object.prototype.hasOwnProperty.call(bundle.intake_draft, "model_metadata")
  ) {
    diagnostics.intake_model_metadata = bundle.intake_draft.model_metadata;
  }

  return {
    result: pickOwn(bundle, VIEW_BUNDLE_FIELDS.result),
    intake: pickOwn(bundle, VIEW_BUNDLE_FIELDS.intake),
    research: pickOwn(bundle, VIEW_BUNDLE_FIELDS.research),
    evidence: pickOwn(bundle, VIEW_BUNDLE_FIELDS.evidence),
    evaluations: pickOwn(bundle, VIEW_BUNDLE_FIELDS.evaluations),
    unresolved: pickOwn(bundle, VIEW_BUNDLE_FIELDS.unresolved),
    diagnostics,
    raw: payload,
  };
}
