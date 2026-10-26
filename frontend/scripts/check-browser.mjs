import { chromium } from "playwright";

// Verify the actual runtime before reinstalling libraries already supplied by
// the CI runner. The full HTTPS/database browser suite still runs afterwards.
const browser = await chromium.launch({ headless: true });
await browser.close();
console.log("Chromium runtime ready.");
