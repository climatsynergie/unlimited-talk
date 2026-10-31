import type {
  Reporter,
  TestCase,
  TestResult,
  TestStep,
} from "@playwright/test/reporter";
import { relative, resolve } from "node:path";

// Public check annotations identify the failing case and source line only.
// Do not publish DOM snapshots, API bodies, input values, error text or tokens.
function failedStep(steps: TestStep[]): TestStep | undefined {
  for (const step of [...steps].reverse()) {
    const nested = failedStep(step.steps);
    if (nested) return nested;
    if (step.error && step.location) return step;
  }
}
function escape(value: string) {
  return value.replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
}
export default class BrowserSummary implements Reporter {
  onTestEnd(test: TestCase, result: TestResult) {
    if (result.status === test.expectedStatus) return;
    if (!["failed", "timedOut"].includes(result.status)) return;
    const location =
      failedStep(result.steps)?.location ||
      result.errors[0]?.location ||
      test.location;
    const path = relative(resolve(process.cwd(), ".."), location.file).replace(
      /\\/g,
      "/",
    );
    const file = path.startsWith("../")
      ? ""
      : `,file=${escape(path)},line=${location.line}`;
    console.log(
      `::error title=Validation navigateur${file}::${escape(test.title)} — ${result.status}`,
    );
  }
}
