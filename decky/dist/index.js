const manifest = {"name":"GameSphere Companion Tool"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

var DefaultContext = {
  color: undefined,
  size: undefined,
  className: undefined,
  style: undefined,
  attr: undefined
};
var IconContext = SP_REACT.createContext && /*#__PURE__*/SP_REACT.createContext(DefaultContext);

var _excluded = ["attr", "size", "title"];
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), true).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: true, configurable: true, writable: true }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == typeof i ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != typeof t || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r); if ("object" != typeof i) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function Tree2Element(tree) {
  return tree && tree.map((node, i) => /*#__PURE__*/SP_REACT.createElement(node.tag, _objectSpread({
    key: i
  }, node.attr), Tree2Element(node.child)));
}
function GenIcon(data) {
  return props => /*#__PURE__*/SP_REACT.createElement(IconBase, _extends({
    attr: _objectSpread({}, data.attr)
  }, props), Tree2Element(data.child));
}
function IconBase(props) {
  var elem = conf => {
    var attr = props.attr,
      size = props.size,
      title = props.title,
      svgProps = _objectWithoutProperties(props, _excluded);
    var computedSize = size || conf.size || "1em";
    var className;
    if (conf.className) className = conf.className;
    if (props.className) className = (className ? className + " " : "") + props.className;
    return /*#__PURE__*/SP_REACT.createElement("svg", _extends({
      stroke: "currentColor",
      fill: "currentColor",
      strokeWidth: "0"
    }, conf.attr, attr, svgProps, {
      className: className,
      style: _objectSpread(_objectSpread({
        color: props.color || conf.color
      }, conf.style), props.style),
      height: computedSize,
      width: computedSize,
      xmlns: "http://www.w3.org/2000/svg"
    }), title && /*#__PURE__*/SP_REACT.createElement("title", null, title), props.children);
  };
  return IconContext !== undefined ? /*#__PURE__*/SP_REACT.createElement(IconContext.Consumer, null, conf => elem(conf)) : elem(DefaultContext);
}

// THIS FILE IS AUTO GENERATED
function FaSatelliteDish (props) {
  return GenIcon({"attr":{"viewBox":"0 0 512 512"},"child":[{"tag":"path","attr":{"d":"M305.44954,462.59c7.39157,7.29792,6.18829,20.09661-3.00038,25.00356-77.713,41.80281-176.72559,29.9105-242.34331-35.7082C-5.49624,386.28227-17.404,287.362,24.41381,209.554c4.89125-9.095,17.68975-10.29834,25.00318-3.00043L166.22872,323.36708l27.39411-27.39452c-.68759-2.60974-1.594-5.00071-1.594-7.81361a32.00407,32.00407,0,1,1,32.00407,32.00455c-2.79723,0-5.20378-.89075-7.79786-1.594l-27.40974,27.41015ZM511.9758,303.06732a16.10336,16.10336,0,0,1-16.002,17.00242H463.86031a15.96956,15.96956,0,0,1-15.89265-15.00213C440.46671,175.5492,336.45348,70.53427,207.03078,63.53328a15.84486,15.84486,0,0,1-15.00191-15.90852V16.02652A16.09389,16.09389,0,0,1,209.031.02425C372.25491,8.61922,503.47472,139.841,511.9758,303.06732Zm-96.01221-.29692a16.21093,16.21093,0,0,1-16.11142,17.29934H367.645a16.06862,16.06862,0,0,1-15.89265-14.70522c-6.90712-77.01094-68.118-138.91037-144.92467-145.22376a15.94,15.94,0,0,1-14.79876-15.89289V112.13393a16.134,16.134,0,0,1,17.29908-16.096C319.45132,104.5391,407.55627,192.64538,415.96359,302.7704Z"},"child":[]}]})(props);
}

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
const runMicPeakTest = callable("run_mic_peak_test");
const launchMicTestUi = callable("launch_mic_test_ui");
const setMicAec = callable("set_mic_aec");
const runDoctor = callable("run_doctor");
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
function formatMicLabel(status, loading) {
    const mic = status?.mic;
    if (!status && loading)
        return "Loading…";
    if (!mic || (!mic.detail && mic.ok === undefined && mic.pipewireSourcePresent === undefined)) {
        return status ? "Idle — appears when voice starts" : "—";
    }
    if (mic.detail)
        return mic.detail;
    if (mic.pcMicReady || mic.pipewireSourcePresent)
        return "GameSphere Mic ready";
    return "Idle — appears when voice starts";
}
function pill(ok, yes, no, unk = "…") {
    if (ok === true)
        return yes;
    if (ok === false)
        return no;
    return unk;
}
function Content() {
    const [dryRun, setDryRun] = SP_REACT.useState(true);
    const [noRestart, setNoRestart] = SP_REACT.useState(false);
    const [hostTuning, setHostTuning] = SP_REACT.useState(false);
    const [removeConfirm, setRemoveConfirm] = SP_REACT.useState(false);
    const [verbose, setVerbose] = SP_REACT.useState(false);
    const [showAdvanced, setShowAdvanced] = SP_REACT.useState(false);
    const [bridgeOn, setBridgeOn] = SP_REACT.useState(false);
    const [autoSyncOn, setAutoSyncOn] = SP_REACT.useState(false);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [loading, setLoading] = SP_REACT.useState(true);
    const [log, setLog] = SP_REACT.useState("");
    const [status, setStatus] = SP_REACT.useState(null);
    const [micPeak, setMicPeak] = SP_REACT.useState(null);
    const describeError = (err) => err instanceof Error ? err.message : String(err);
    const refreshStatus = SP_REACT.useCallback(async () => {
        setLoading(true);
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
        finally {
            setLoading(false);
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
    const onAecToggle = async (enabled) => {
        setBusy(true);
        try {
            const result = await setMicAec(enabled);
            setLog(result.output ||
                (result.ok
                    ? enabled
                        ? "AEC on — verify levels with Test mic (peak)."
                        : "AEC off — raw uplink (recommended)."
                    : "AEC toggle failed."));
            await refreshStatus();
        }
        catch (err) {
            setLog(`AEC toggle failed: ${describeError(err)}`);
        }
        finally {
            setBusy(false);
        }
    };
    const onMicPeakTest = async () => {
        setBusy(true);
        setMicPeak(null);
        try {
            setLog("Mic test: speak now for ~3 seconds…");
            const result = await runMicPeakTest(3);
            setMicPeak(result);
            setLog(result.detail || (result.ok ? "Mic test done." : "Mic test failed."));
            await refreshStatus();
        }
        catch (err) {
            setLog(`Mic test failed: ${describeError(err)}`);
        }
        finally {
            setBusy(false);
        }
    };
    const onMicTestUi = async () => {
        setBusy(true);
        try {
            const result = await launchMicTestUi();
            setLog(result.detail || (result.ok ? "Mic Test launched." : "Could not open Mic Test."));
        }
        catch (err) {
            setLog(`Mic Test launch failed: ${describeError(err)}`);
        }
        finally {
            setBusy(false);
        }
    };
    SP_REACT.useEffect(() => {
        void refreshStatus();
    }, [refreshStatus]);
    // Assume installed while loading so quick actions stay visible (status null ≠ missing CLI).
    const installed = status === null ? true : Boolean(status.installed);
    const hostLabel = status?.paths?.GAMESPHERE_HOST_LABEL || status?.paths?.host_label || "";
    const linkMbps = status?.host_tuning?.link?.current_mbps;
    const sessions = status?.host_tuning?.sessions_count ?? 0;
    const mic = status?.mic;
    const wan = status?.host_tuning?.wan;
    const bridgeOk = status?.bridge_service === "active";
    const micOk = mic?.pipewireSourcePresent === true || mic?.pcMicReady === true || mic?.ok === true;
    return (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsxs(DFL.PanelSection, { title: "Overview", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Companion", children: loading && status === null
                                ? "Loading…"
                                : status === null
                                    ? "Status unavailable — tap Refresh"
                                    : installed
                                        ? status.version || "Installed"
                                        : "Not installed — run install-linux.sh" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "At a glance", children: loading && status === null
                                ? "Loading…"
                                : [
                                    `Bridge ${pill(bridgeOk, "on", status?.bridge_service || "off")}`,
                                    `Mic ${pill(micOk, "ready", "idle")}`,
                                    linkMbps ? `${linkMbps} Mbps` : null,
                                    hostLabel || null,
                                ]
                                    .filter(Boolean)
                                    .join(" · ") || "—" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Sync", () => runLibrarySyncNow()), disabled: busy || !installed, children: "Sync Steam library now" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: onMicPeakTest, disabled: busy || !installed, children: busy && !micPeak ? "Testing mic…" : "Test mic (3s peak)" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: onMicTestUi, disabled: busy || !installed, children: "Open Mic Test (fullscreen)" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: refreshStatus, disabled: busy || loading, children: loading ? "Refreshing…" : "Refresh status" }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Microphone", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Status", children: formatMicLabel(status, loading) }) }), micPeak ? (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Last peak test", children: typeof micPeak.peak_pct === "number"
                                ? `${micPeak.peak_pct}% · ${micPeak.source || "mic"}`
                                : micPeak.detail || "—" }) })) : null, SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs(DFL.Field, { label: "PipeWire source", children: [mic?.pipewireSourcePresent === true
                                    ? mic.pcMicSource || "gamesphere_mic"
                                    : mic?.pipewireSourcePresent === false
                                        ? "Missing"
                                        : loading
                                            ? "Loading…"
                                            : "—", mic?.voiceRunning ? " · voice running" : "", typeof mic?.clients === "number" && mic.clients > 0
                                    ? ` · ${mic.clients} client(s)`
                                    : ""] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Gameplay cancel (AEC)", description: mic?.aec
                                ? "WebRTC vs HDMI monitor — re-check peak after enabling"
                                : "Off (recommended) — raw phone uplink", checked: Boolean(mic?.aec), onChange: onAecToggle, disabled: busy || !installed }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Mic setup", () => runSetupMic()), disabled: busy || !installed, children: "Set up GameSphere Mic" }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Library", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Auto-sync new Steam games (~15 min)", checked: autoSyncOn, onChange: onAutoSyncToggle, disabled: busy || !installed }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.Field, { label: "Last auto-sync", children: formatSyncLabel(status) }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Show import options", checked: showAdvanced, onChange: setShowAdvanced }) }), showAdvanced ? (SP_JSX.jsxs(SP_JSX.Fragment, { children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Dry run (preview only)", checked: dryRun, onChange: setDryRun }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Skip Sunshine restart", checked: noRestart, onChange: setNoRestart }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Apply host tuning after import", checked: hostTuning, onChange: setHostTuning }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Verbose log", checked: verbose, onChange: setVerbose }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Import", () => runImport(dryRun, noRestart, hostTuning && !dryRun, verbose)), disabled: busy || !installed, children: busy
                                        ? "Running…"
                                        : dryRun
                                            ? "Preview full import"
                                            : "Full import (Steam + shortcuts)" }) })] })) : null] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Host", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ToggleField, { label: "Host bridge (TCP 47998)", description: "JOINPIN, couch coop, WAN, in-stream voice", checked: bridgeOn, onChange: onBridgeToggle, disabled: busy || !installed }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs(DFL.Field, { label: "Host tuning", children: [status?.host_tuning?.enabled ? "Enabled" : "Disabled", linkMbps ? ` · ${linkMbps} Mbps` : "", sessions ? ` · ${sessions} session(s)` : ""] }) }), wan ? (SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs(DFL.Field, { label: "WAN maps", children: [wan.wanReady
                                    ? `Ready · ${wan.mapper || wan.status || "ok"}`
                                    : wan.status || "Not mapped", wan.wanHost ? ` · ${wan.wanHost}` : ""] }) })) : null, SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Doctor", () => runDoctor()), disabled: busy || !installed, children: "Run health check (doctor)" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Host tuning", () => runHostTuningOnly()), disabled: busy || !installed, children: "Apply host tuning" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Host tuning init", () => initHostTuning()), disabled: busy || !installed, children: "Initialize host tuning defaults" }) })] }), SP_JSX.jsxs(DFL.PanelSection, { title: "Updates & maintenance", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Update check", () => runCheckUpdate()), disabled: busy || !installed, children: "Check for updates" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Update", () => runApplyUpdate()), disabled: busy || !installed, children: "Install latest release" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => runAction("Refresh paths", () => runRefreshConfig()), disabled: busy || !installed, children: "Regenerate .env from detected paths" }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx(DFL.ButtonItem, { layout: "below", onClick: () => {
                                if (!removeConfirm) {
                                    setRemoveConfirm(true);
                                    setLog("Confirm: tap again to remove ALL games (keeps Desktop + Big Picture only).");
                                    return;
                                }
                                setRemoveConfirm(false);
                                runAction("Remove games", () => runRemove());
                            }, disabled: busy || !installed, children: removeConfirm
                                ? "Confirm remove all games"
                                : "Remove all games (stock apps only)" }) })] }), log ? (SP_JSX.jsx(DFL.PanelSection, { title: "Log", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("pre", { style: {
                            whiteSpace: "pre-wrap",
                            fontSize: "0.82em",
                            maxHeight: "40vh",
                            overflow: "auto",
                        }, children: log }) }) })) : null] }));
}
var index = definePlugin(() => ({
    name: "GameSphere Companion Tool",
    titleView: (SP_JSX.jsx("div", { className: DFL.staticClasses.Title, children: "GameSphere Companion Tool" })),
    content: SP_JSX.jsx(Content, {}),
    icon: SP_JSX.jsx(FaSatelliteDish, {}),
    onDismount() { },
}));

export { index as default };
//# sourceMappingURL=index.js.map
