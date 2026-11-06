// Starts a "schedule" wake of the reels workflow. The gate in the workflow decides whether a reel is due.
// GH_DISPATCH_TOKEN: fine-grained GitHub token, this repo only, Actions read and write (set by scripts/set_trigger.sh).
const URL = "https://api.github.com/repos/het-dave/trivia-reels-automation/actions/workflows/reels.yml/dispatches";

export default {
  async scheduled(_event, env) {
    const r = await fetch(URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "trivia-reels-trigger",
      },
      body: JSON.stringify({ ref: "main", inputs: { mode: "schedule" } }),
    });
    if (!r.ok) throw new Error(`workflow_dispatch HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
  },
};
