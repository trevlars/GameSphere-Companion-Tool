import { callable } from '@decky/api';

const getStatus = callable("get_status");
const runImport = callable("run_import");
const runHostTuningOnly = callable("run_host_tuning_only");
const runRemove = callable("run_remove");
const runRefreshConfig = callable("run_refresh_config");
const runCheckUpdate = callable("run_check_update");
const runApplyUpdate = callable("run_apply_update");
const setBridgeEnabled = callable("set_bridge_enabled");
const setLibrarySyncEnabled = callable("set_library_sync_enabled");
const runLibrarySyncNow = callable("run_library_sync_now");
const runSetupMic = callable("run_setup_mic");
const initHostTuning = callable("init_host_tuning");
function formatSyncLabel(status) {
    const sync = status?.library_sync;
    if (!sync || sync.ever_run === false || (!sync.iso && !sync.message)) {
        return "Never ran";
    }
    const when = sync.iso ? sync.iso.replace("T", " ").slice(0, 19) : "";
    const bits = [];
    if (when)
        bits.push(when);
    if (typeof sync.added === "number" && sync.added > 0)
        bits.push(`+${sync.added}`);
    if (typeof sync.removed === "number" && sync.removed > 0)
        bits.push(`-${sync.removed}`);
    if (sync.message)
        bits.push(sync.message);
    return bits.join(" · ") || "—";
}
function formatMicLabel(status) {
    const mic = status?.mic;
    if (!mic)
        return "…";
    const aec = mic.aec ? " · AEC on (HDMI monitor)" : "";
    if (mic.detail)
        return `${mic.detail}${aec}`;
    if (mic.pcMicReady || mic.pipewireSourcePresent)
        return `GameSphere Mic ready${aec}`;
    return "Idle — appears when voice starts";
}
function Content() {
    const [dryRun, setDryRun] = SP_REACT.useState(true);
    const [noRestart, setNoRestart] = SP_REACT.useState(false);
    const [hostTuning, setHostTuning] = SP_REACT.useState(false);
    const [removeConfirm, setRemoveConfirm] = SP_REACT.useState(false);
    const [verbose, setVerbose] = SP_REACT.useState(false);
    const [bridgeOn, setBridgeOn] = SP_REACT.useState(false);
    const [autoSyncOn, setAutoSyncOn] = SP_REACT.useState(false);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [log, setLog] = SP_REACT.useState("");
    const [status, setStatus] = SP_REACT.useState(null);
    // A rejected callable (backend reload, missing binary) must surface as text
    // instead of an unhandled rejection that leaves the panel blank.
    const describeError = (err) => err instanceof Error ? err.message : String(err);
    const refreshStatus = SP_REACT.useCallback(async () => {
        try {
            const s = await getStatus();
            setStatus(s);
            setBridgeOn(s.bridge_service === "active");
            const timer = s.library_sync_timer || "";
            setAutoSyncOn(timer === "active" || timer === "waiting");
        }
        catch (err) {
            setLog(`Could not read Companion status: ${describeError(err)}`);
        }
    }, []);
    const runAction = async (label, fn) => {
        setBusy(true);
        try {
            const result = await fn();
            const text = result.output || (result.ok ? `${label} done.` : `${label} failed.`);
            setLog(result.banner ? `${result.banner}\n\n${text}` : text);
            await refreshStatus();
        }
        catch (err) {
            setLog(`${label} failed: ${describeError(err)}`);
        }
        finally {
            setBusy(false);
        }
    };
    const onBridgeToggle = async (enabled) => {
        setBusy(true);
        try {
            const result = await setBridgeEnabled(enabled);
            setBridgeOn(result.state === "active");
            setLog(result.output || (result.ok ? "Bridge updated." : "Bridge toggle failed."));
            await refreshStatus();
        }
        catch (err) {
            setLog(`Bridge toggle failed: ${describeError(err)}`);
            await refreshStatus();
        }
        finally {
            setBusy(false);
        }
    };
    const onAutoSyncToggle = async (enabled) => {
        setBusy(true);
        try {
            const result = await setLibrarySyncEnabled(enabled);
            const state = result.state || "";
            setAutoSyncOn(state === "active" || state === "waiting");
            setLog(result.output ||
                (result.ok
                    ? enabled
                        ? "Auto-sync on — new Steam games land in Sunshine ~every 15 minutes."
                        : "Auto-sync off."
                    : "Auto-sync toggle failed."));
            await refreshStatus();
        }
        catch (err) {
            setLog(`Auto-sync toggle failed: ${describeError(err)}`);
            await refreshStatus();
        }
        finally {
            setBusy(false);
        }
    };
    SP_REACT.useEffect(() => {
        void refreshStatus();
    }, [refreshStatus]);
    const installed = status?.installed ?? false;
    const hostLabel = status?.paths?.GAMESPHERE_HOST_LABEL || status?.paths?.host_label || "";
    const appsPath = status?.paths?.sunshine_apps_json_path || "—";
    const linkMbps = status?.host_tuning?.link?.current_mbps;
    const sessions = status?.host_tuning?.sessions_count ?? 0;
    const mic = status?.mic;
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsxs(DFL.PanelSection, { title: "Status", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Companion Tool", children: status === null
                                ? "…"
                                : installed
                                    ? status.version || "Installed"
                                    : "Not installed — run install-linux.sh" }) }), installed ? (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Host profile", children: hostLabel || "linux" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "apps.json", children: appsPath }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs(DFL.Field, { label: "Bridge (TCP 47998)", children: [status?.bridge_service || "unknown", status?.bridge_unit_installed ? "" : " — unit not installed yet"] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs(DFL.Field, { label: "Host tuning", children: [status?.host_tuning?.enabled ? "Enabled" : "Disabled", linkMbps ? ` · ${linkMbps} Mbps` : "", sessions ? ` · ${sessions} session(s) logged` : ""] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: refreshStatus, disabled: busy, children: "Refresh status" }) })] })) : null] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Mic (GameSphere Mic)", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Status", children: formatMicLabel(status) }) }), installed && mic ? (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs(DFL.Field, { label: "PipeWire source", children: [mic.pipewireSourcePresent === true
                                            ? "Present"
                                            : mic.pipewireSourcePresent === false
                                                ? "Missing"
                                                : "—", mic.voiceRunning ? " · voice running" : "", typeof mic.clients === "number" && mic.clients > 0
                                            ? ` · ${mic.clients} client(s)`
                                            : ""] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Gameplay cancel (AEC)", children: mic.aec
                                        ? "WebRTC vs HDMI monitor — speakers OK"
                                        : "Off — game audio may bleed into Discord" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Mic setup", () => runSetupMic()), disabled: busy || !installed, children: "Set up GameSphere Mic + AEC" }) })] })) : null] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Sync Steam library", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Auto-sync new Steam games (~15 min)", checked: autoSyncOn, onChange: onAutoSyncToggle, disabled: busy || !installed }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Last auto-sync", children: formatSyncLabel(status) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Auto-sync", () => runLibrarySyncNow()), disabled: busy || !installed, children: "Sync now (no Sunshine restart)" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Dry run (preview only)", checked: dryRun, onChange: setDryRun }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Skip Sunshine restart", checked: noRestart, onChange: setNoRestart }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Apply host tuning after import", checked: hostTuning, onChange: setHostTuning }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Verbose log", checked: verbose, onChange: setVerbose }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Import", () => runImport(dryRun, noRestart, hostTuning && !dryRun, verbose)), disabled: busy || !installed, children: busy
                                ? "Running…"
                                : dryRun
                                    ? "Preview import"
                                    : "Import Steam + shortcuts" }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Host tuning", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Host tuning init", () => initHostTuning()), disabled: busy || !installed, children: "Initialize host tuning (enable all)" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Host tuning", () => runHostTuningOnly()), disabled: busy || !installed, children: "Apply host tuning only" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "GameSphere bridge service (TCP 47998)", checked: bridgeOn, onChange: onBridgeToggle, disabled: busy || !installed }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Maintenance", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Refresh paths", () => runRefreshConfig()), disabled: busy || !installed, children: "Regenerate .env from detected paths" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Update check", () => runCheckUpdate()), disabled: busy || !installed, children: "Check for updates" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Update", () => runApplyUpdate()), disabled: busy || !installed, children: "Install latest release" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => {
                                if (!removeConfirm) {
                                    setRemoveConfirm(true);
                                    setLog("Confirm: tap again to remove ALL games (keeps Desktop + Big Picture only).");
                                    return;
                                }
                                setRemoveConfirm(false);
                                runAction("Remove games", () => runRemove());
                            }, disabled: busy || !installed, children: removeConfirm ? "Confirm remove all games" : "Remove all games (stock apps only)" }) })] }), log ? (SP_JSX.jsx(DFL.PanelSection, { title: "Log", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("pre", { style: { whiteSpace: "pre-wrap", fontSize: "0.82em", maxHeight: "40vh", overflow: "auto" }, children: log }) }) })) : null] }));
}
var index = DFL.definePlugin(() => ({
    title: SP_JSX.jsx("div", { className: "gamesphere-companion-title", children: "GameSphere Companion" }),
    content: SP_JSX.jsx(Content, {}),
    icon: "https://raw.githubusercontent.com/trevlars/GameSphere-Companion-Tool/main/assets/readme-screenshot.png",
    onDismount() { },
}));

export { index as default };
//# sourceMappingURL=index.js.map
