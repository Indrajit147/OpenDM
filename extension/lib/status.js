// Turn the reply to a "status" request into what the popup and options page show.
// A store install usually comes before the app, so "not installed" needs its own message.

export const GET_OPENDM_URL = "https://github.com/Indrajit147/OpenDM/releases/latest";

export function connectionState(reply) {
  if (reply?.ok) return { state: "connected", text: "Connected to OpenDM" };
  const message = String(reply?.message || "").toLowerCase();
  if (message.includes("not found")) {
    return {
      state: "not-installed",
      text: "The OpenDM app is not installed (or not set up). Install it, then in OpenDM open Settings > Browser and click Set up.",
      link: GET_OPENDM_URL,
    };
  }
  if (message.includes("forbidden")) {
    return {
      state: "outdated",
      text: "Your OpenDM does not know this extension yet. Update OpenDM, then open Settings > Browser and click Repair.",
      link: GET_OPENDM_URL,
    };
  }
  return { state: "not-running", text: "OpenDM is not running. Start it from the Start menu." };
}
