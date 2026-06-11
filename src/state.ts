/**
 * Wizard state for the main Speakspec flow:
 * record -> transcribe -> transcript review -> constraint review ->
 * interview-back -> generate (stages 2+3) -> results.
 *
 * One store, mutated only through the exported actions, so the flow logic
 * stays testable and components stay dumb.
 */
import { createStore } from "solid-js/store";
import {
  runPipelineStage,
  saveSession,
  transcribe as ipcTranscribe,
  type StageResponse,
  type TranscribeResult,
} from "./lib/ipc";

/** Mirrors the Stage 1 schema (subset the UI touches). */
export interface Constraint {
  category: string;
  value: string;
  source: "stated" | "inferred";
  confidence: "high" | "medium" | "low";
}

export interface InterviewQuestion {
  question: string;
  why_it_matters: string;
}

export interface Stage1Result {
  intent_summary: string;
  core_intent: string;
  analogies: Array<{ comparison: string; implication: string }>;
  named_components: string[];
  constraints: Constraint[];
  open_questions: string[];
  interview_questions: InterviewQuestion[];
}

/** All 11 categories, in display order (mirrors the locked schema enum). */
export const ALL_CATEGORIES = [
  "deployment_target",
  "team_size",
  "latency_requirement",
  "scale_expectation",
  "ops_complexity_budget",
  "ship_timeline",
  "external_integrations",
  "language_preference",
  "persistence_requirements",
  "security_posture",
  "quality_goals",
] as const;

export type Step =
  | "record"
  | "transcribing"
  | "transcript"
  | "constraints"
  | "interview"
  | "generating"
  | "results";

export interface AppState {
  step: Step;
  audioPath: string | null;
  sessionDir: string | null;
  transcriptResult: TranscribeResult | null;
  /** The editable transcript; edits persist through the whole pipeline. */
  transcript: string;
  stage1: Stage1Result | null;
  /** Marks that the user has actually seen the review screen. */
  constraintsReviewed: boolean;
  template: string;
  interviewAnswers: string[];
  stage2: Record<string, unknown> | null;
  stage3: Record<string, unknown> | null;
  diagramReports: Array<Record<string, unknown>>;
  agentsGateReport: Record<string, unknown> | null;
  /** Streaming token tail shown during generation. */
  tokenTail: string;
  activeStage: number;
  error: string | null;
  busy: boolean;
}

const [state, setState] = createStore<AppState>({
  step: "record",
  audioPath: null,
  sessionDir: null,
  transcriptResult: null,
  transcript: "",
  stage1: null,
  constraintsReviewed: false,
  template: "Solo MVP",
  interviewAnswers: [],
  stage2: null,
  stage3: null,
  diagramReports: [],
  agentsGateReport: null,
  tokenTail: "",
  activeStage: 0,
  error: null,
  busy: false,
});

export { state };

/** Reset to a fresh session (keeps nothing). */
export function resetSession(): void {
  setState({
    step: "record",
    audioPath: null,
    sessionDir: null,
    transcriptResult: null,
    transcript: "",
    stage1: null,
    constraintsReviewed: false,
    interviewAnswers: [],
    stage2: null,
    stage3: null,
    diagramReports: [],
    agentsGateReport: null,
    tokenTail: "",
    activeStage: 0,
    error: null,
    busy: false,
  });
}

export function setError(message: string | null): void {
  setState({ error: message, busy: false });
}

export function appendToken(text: string): void {
  setState("tokenTail", (tail) => (tail + text).slice(-600));
}

/** Audio finished (recorded or imported): transcribe it. */
export async function audioReady(path: string, sessionDir: string): Promise<void> {
  setState({ audioPath: path, sessionDir, step: "transcribing", error: null, busy: true });
  try {
    const result = await ipcTranscribe({ audio_path: path });
    setState({
      transcriptResult: result,
      transcript: result.transcript,
      step: "transcript",
      busy: false,
    });
  } catch (err) {
    setState({ step: "record", busy: false, error: errorText(err) });
  }
}

/** Transcript approved (possibly edited): run Stage 1. */
export async function transcriptApproved(): Promise<void> {
  setState({ step: "constraints", busy: true, error: null, tokenTail: "", activeStage: 1 });
  try {
    const response = await runPipelineStage<Stage1Result>(1, {
      transcript: state.transcript,
    });
    setState({ stage1: response.result, busy: false, constraintsReviewed: true });
  } catch (err) {
    setState({ step: "transcript", busy: false, error: errorText(err) });
  }
}

/** Inline-edit one constraint field; persists into Stage 2 input. */
export function editConstraint(index: number, patch: Partial<Constraint>): void {
  setState("stage1", "constraints", index, patch);
}

export function setTranscript(text: string): void {
  setState("transcript", text);
}

export function setTemplate(name: string): void {
  setState("template", name);
}

export function setAnswer(index: number, text: string): void {
  setState("interviewAnswers", index, text);
}

/** Constraint review done: move to interview-back. */
export function constraintsApproved(): void {
  const questions = state.stage1?.interview_questions ?? [];
  setState({
    step: "interview",
    interviewAnswers: questions.map(() => ""),
  });
}

/** Interview answered (or skipped): run Stages 2 and 3. */
export async function startGeneration(): Promise<void> {
  if (!state.stage1) return;
  const answers = state.stage1.interview_questions
    .map((q, i) => {
      const answer = state.interviewAnswers[i]?.trim();
      return answer ? `Q: ${q.question}\nA: ${answer}` : null;
    })
    .filter(Boolean)
    .join("\n\n");

  setState({ step: "generating", busy: true, error: null, tokenTail: "", activeStage: 2 });
  try {
    const stage2: StageResponse<Record<string, unknown>> = await runPipelineStage(2, {
      constraints: state.stage1,
      interview_answers: answers,
      template: state.template,
    });
    setState({ stage2: stage2.result, activeStage: 3, tokenTail: "" });
    const stage3 = await runPipelineStage<Record<string, unknown>>(3, {
      architecture_spec: stage2.result,
    });
    const raw = stage3 as unknown as {
      result: Record<string, unknown>;
      diagram_reports?: Array<Record<string, unknown>>;
    };
    setState({
      stage3: raw.result,
      diagramReports: raw.diagram_reports ?? [],
      step: "results",
      busy: false,
      activeStage: 0,
    });
    void persistSession();
  } catch (err) {
    setState({ step: "interview", busy: false, error: errorText(err) });
  }
}

/** Auto-save the finished session into the library (best effort). */
async function persistSession(): Promise<void> {
  const dir = state.sessionDir;
  if (!dir) return;
  const id = dir.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? String(Date.now());
  try {
    await saveSession({
      id,
      title: state.stage1?.core_intent?.slice(0, 120) ?? "Untitled session",
      transcript: state.transcript,
      specJson: JSON.stringify({ stage2: state.stage2, stage3: state.stage3 }),
      dir,
    });
  } catch (err) {
    console.warn("session save failed:", err);
  }
}

/** Re-open a stored session in the results view. */
export function openStoredSession(transcript: string, specJson: string, dir: string): void {
  try {
    const parsed = JSON.parse(specJson) as {
      stage2?: Record<string, unknown>;
      stage3?: Record<string, unknown>;
    };
    setState({
      transcript,
      sessionDir: dir,
      stage2: parsed.stage2 ?? null,
      stage3: parsed.stage3 ?? null,
      diagramReports: [],
      step: parsed.stage3 ? "results" : "record",
      error: parsed.stage3 ? null : "This session has no stored spec; start a new run.",
    });
  } catch {
    setError("This session's stored spec could not be parsed.");
  }
}

/** Stable error text from an AppError or anything else. */
export function errorText(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    const e = err as { code?: string; message: string };
    return e.code ? `${e.message} (${e.code})` : e.message;
  }
  return String(err);
}
