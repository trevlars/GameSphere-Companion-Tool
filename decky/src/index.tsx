import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaSatelliteDish } from "react-icons/fa";

type Status = {
  installed: boolean;
  version?: string;
  install_kind?: string;
  paths?: Record<string, string>;
  host_tuning?: {
    enabled?: boolean;
    adapter?: string;
    sessions_count?: number;
    link?: { current_mbps?: number };
    wan?: {
      wanReady?: boolean;
      status?: string;
      mapper?: string;
      lanHost?: string;
      wanHost?: string;
    };
  };
  bridge_service?: string;
  bridge_unit_installed?: boolean;
  library_sync_timer?: string;
  library_sync?: {
    ok?: boolean | null;
    message?: string;
    added?: number;
    removed?: number;
    changed?: boolean;
    iso?: string;
    ever_run?: boolean;
    timer?: { active?: boolean; enabled?: boolean; active_state?: string };
  };
  mic?: {
    ok?: boolean;
    detail?: string;
    device?: string;
    voiceRunning?: boolean;
    pcMicReady?: boolean;
    pipewireSourcePresent?: boolean | null;
    clients?: number;
    aec?: boolean;
    aecMode?: string;
    pcMicSource?: string;
  };
};

type RunResult = { ok: boolean; output: string; banner?: string };
type MicTestResult = {
  ok: boolean;
  detail?: string;
  source?: string;
  peak_pct?: number;
  seconds?: number;
};

const getStatus = callable<[], Status>("get_status");
const runImport = callable<[boolean, boolean, boolean, boolean], RunResult>("run_import");
const runHostTuningOnly = callable<[], RunResult>("run_host_tuning_only");
const runRemove = callable<[], RunResult>("run_remove");
const runRefreshConfig = callable<[], RunResult>("run_refresh_config");
const runCheckUpdate = callable<[], RunResult>("run_check_update");
const runApplyUpdate = callable<[], RunResult>("run_apply_update");
const setBridgeEnabled = callable<[boolean], { ok: boolean; output: string; state?: string }>(
  "set_bridge_enabled"
);
const setLibrarySyncEnabled = callable<
  [boolean],
  { ok: boolean; output: string; state?: string }
>("set_library_sync_enabled");
const runLibrarySyncNow = callable<[], RunResult>("run_library_sync_now");
const runSetupMic = callable<[], RunResult>("run_setup_mic");
const runMicPeakTest = callable<[number], MicTestResult>("run_mic_peak_test");
const launchMicTestUi = callable<[], MicTestResult>("launch_mic_test_ui");
const setMicAec = callable<[boolean], { ok: boolean; output: string }>("set_mic_aec");
const runDoctor = callable<[], RunResult>("run_doctor");
const initHostTuning = callable<[], RunResult>("init_host_tuning");

function formatSyncLabel(status: Status | null): string {
  const sync = status?.library_sync;
  if (!sync || sync.ever_run === false || (!sync.iso && !sync.message)) {
    return "Never ran";
  }
  const when = sync.iso ? sync.iso.replace("T", " ").slice(0, 19) : "";
  const bits: string[] = [];
  if (when) bits.push(when);
  if (typeof sync.added === "number" && sync.added > 0) bits.push(`+${sync.added}`);
  if (typeof sync.removed === "number" && sync.removed > 0) bits.push(`-${sync.removed}`);
  if (sync.message) bits.push(sync.message);
  return bits.join(" · ") || "—";
}

function formatMicLabel(status: Status | null, loading: boolean): string {
  const mic = status?.mic;
  if (!status && loading) return "Loading…";
  if (!mic || (!mic.detail && mic.ok === undefined && mic.pipewireSourcePresent === undefined)) {
    return status ? "Idle — appears when voice starts" : "—";
  }
  if (mic.detail) return mic.detail;
  if (mic.pcMicReady || mic.pipewireSourcePresent) return "GameSphere Mic ready";
  return "Idle — appears when voice starts";
}

function pill(ok: boolean | null | undefined, yes: string, no: string, unk = "…"): string {
  if (ok === true) return yes;
  if (ok === false) return no;
  return unk;
}

function Content() {
  const [dryRun, setDryRun] = useState(true);
  const [noRestart, setNoRestart] = useState(false);
  const [hostTuning, setHostTuning] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState(false);
  const [verbose, setVerbose] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [bridgeOn, setBridgeOn] = useState(false);
  const [autoSyncOn, setAutoSyncOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [log, setLog] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [micPeak, setMicPeak] = useState<MicTestResult | null>(null);

  const describeError = (err: unknown): string =>
    err instanceof Error ? err.message : String(err);

  const refreshStatus = useCallback(async () => {
    setLoading(true);
    try {
      const s = await getStatus();
      setStatus(s);
      setBridgeOn(s.bridge_service === "active");
      const timer = s.library_sync_timer || "";
      setAutoSyncOn(timer === "active" || timer === "waiting");
    } catch (err) {
      setLog(`Could not read Companion status: ${describeError(err)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const runAction = async (
    label: string,
    fn: () => Promise<RunResult | { ok: boolean; output: string; banner?: string }>
  ) => {
    setBusy(true);
    try {
      const result = await fn();
      const text = result.output || (result.ok ? `${label} done.` : `${label} failed.`);
      setLog(result.banner ? `${result.banner}\n\n${text}` : text);
      await refreshStatus();
    } catch (err) {
      setLog(`${label} failed: ${describeError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const onBridgeToggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      const result = await setBridgeEnabled(enabled);
      setBridgeOn(result.state === "active");
      setLog(result.output || (result.ok ? "Bridge updated." : "Bridge toggle failed."));
      await refreshStatus();
    } catch (err) {
      setLog(`Bridge toggle failed: ${describeError(err)}`);
      await refreshStatus();
    } finally {
      setBusy(false);
    }
  };

  const onAutoSyncToggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      const result = await setLibrarySyncEnabled(enabled);
      const state = result.state || "";
      setAutoSyncOn(state === "active" || state === "waiting");
      setLog(
        result.output ||
          (result.ok
            ? enabled
              ? "Auto-sync on — new Steam games land in Sunshine ~every 15 minutes."
              : "Auto-sync off."
            : "Auto-sync toggle failed.")
      );
      await refreshStatus();
    } catch (err) {
      setLog(`Auto-sync toggle failed: ${describeError(err)}`);
      await refreshStatus();
    } finally {
      setBusy(false);
    }
  };

  const onAecToggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      const result = await setMicAec(enabled);
      setLog(
        result.output ||
          (result.ok
            ? enabled
              ? "AEC on — verify levels with Test mic (peak)."
              : "AEC off — raw uplink (recommended)."
            : "AEC toggle failed.")
      );
      await refreshStatus();
    } catch (err) {
      setLog(`AEC toggle failed: ${describeError(err)}`);
    } finally {
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
    } catch (err) {
      setLog(`Mic test failed: ${describeError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const onMicTestUi = async () => {
    setBusy(true);
    try {
      const result = await launchMicTestUi();
      setLog(result.detail || (result.ok ? "Mic Test launched." : "Could not open Mic Test."));
    } catch (err) {
      setLog(`Mic Test launch failed: ${describeError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
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
  const micOk =
    mic?.pipewireSourcePresent === true || mic?.pcMicReady === true || mic?.ok === true;

  return (
    <>
      <PanelSection title="Overview">
        <PanelSectionRow>
          <Field label="Companion">
            {loading && status === null
              ? "Loading…"
              : status === null
              ? "Status unavailable — tap Refresh"
              : installed
              ? status.version || "Installed"
              : "Not installed — run install-linux.sh"}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="At a glance">
            {loading && status === null
              ? "Loading…"
              : [
                  `Bridge ${pill(bridgeOk, "on", status?.bridge_service || "off")}`,
                  `Mic ${pill(micOk, "ready", "idle")}`,
                  linkMbps ? `${linkMbps} Mbps` : null,
                  hostLabel || null,
                ]
                  .filter(Boolean)
                  .join(" · ") || "—"}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Sync", () => runLibrarySyncNow())}
            disabled={busy || !installed}
          >
            Sync Steam library now
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onMicPeakTest} disabled={busy || !installed}>
            {busy && !micPeak ? "Testing mic…" : "Test mic (3s peak)"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onMicTestUi} disabled={busy || !installed}>
            Open Mic Test (fullscreen)
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={refreshStatus} disabled={busy || loading}>
            {loading ? "Refreshing…" : "Refresh status"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Microphone">
        <PanelSectionRow>
          <Field label="Status">{formatMicLabel(status, loading)}</Field>
        </PanelSectionRow>
        {micPeak ? (
          <PanelSectionRow>
            <Field label="Last peak test">
              {typeof micPeak.peak_pct === "number"
                ? `${micPeak.peak_pct}% · ${micPeak.source || "mic"}`
                : micPeak.detail || "—"}
            </Field>
          </PanelSectionRow>
        ) : null}
        <PanelSectionRow>
          <Field label="PipeWire source">
            {mic?.pipewireSourcePresent === true
              ? mic.pcMicSource || "gamesphere_mic"
              : mic?.pipewireSourcePresent === false
              ? "Missing"
              : loading
              ? "Loading…"
              : "—"}
            {mic?.voiceRunning ? " · voice running" : ""}
            {typeof mic?.clients === "number" && mic.clients > 0
              ? ` · ${mic.clients} client(s)`
              : ""}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Gameplay cancel (AEC)"
            description={
              mic?.aec
                ? "WebRTC vs HDMI monitor — re-check peak after enabling"
                : "Off (recommended) — raw phone uplink"
            }
            checked={Boolean(mic?.aec)}
            onChange={onAecToggle}
            disabled={busy || !installed}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Mic setup", () => runSetupMic())}
            disabled={busy || !installed}
          >
            Set up GameSphere Mic
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Library">
        <PanelSectionRow>
          <ToggleField
            label="Auto-sync new Steam games (~15 min)"
            checked={autoSyncOn}
            onChange={onAutoSyncToggle}
            disabled={busy || !installed}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Last auto-sync">{formatSyncLabel(status)}</Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Show import options"
            checked={showAdvanced}
            onChange={setShowAdvanced}
          />
        </PanelSectionRow>
        {showAdvanced ? (
          <>
            <PanelSectionRow>
              <ToggleField
                label="Dry run (preview only)"
                checked={dryRun}
                onChange={setDryRun}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Skip Sunshine restart"
                checked={noRestart}
                onChange={setNoRestart}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Apply host tuning after import"
                checked={hostTuning}
                onChange={setHostTuning}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField label="Verbose log" checked={verbose} onChange={setVerbose} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() =>
                  runAction("Import", () =>
                    runImport(dryRun, noRestart, hostTuning && !dryRun, verbose)
                  )
                }
                disabled={busy || !installed}
              >
                {busy
                  ? "Running…"
                  : dryRun
                  ? "Preview full import"
                  : "Full import (Steam + shortcuts)"}
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : null}
      </PanelSection>

      <PanelSection title="Host">
        <PanelSectionRow>
          <ToggleField
            label="Host bridge (TCP 47998)"
            description="JOINPIN, couch coop, WAN, in-stream voice"
            checked={bridgeOn}
            onChange={onBridgeToggle}
            disabled={busy || !installed}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Host tuning">
            {status?.host_tuning?.enabled ? "Enabled" : "Disabled"}
            {linkMbps ? ` · ${linkMbps} Mbps` : ""}
            {sessions ? ` · ${sessions} session(s)` : ""}
          </Field>
        </PanelSectionRow>
        {wan ? (
          <PanelSectionRow>
            <Field label="WAN maps">
              {wan.wanReady
                ? `Ready · ${wan.mapper || wan.status || "ok"}`
                : wan.status || "Not mapped"}
              {wan.wanHost ? ` · ${wan.wanHost}` : ""}
            </Field>
          </PanelSectionRow>
        ) : null}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Doctor", () => runDoctor())}
            disabled={busy || !installed}
          >
            Run health check (doctor)
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Host tuning", () => runHostTuningOnly())}
            disabled={busy || !installed}
          >
            Apply host tuning
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Host tuning init", () => initHostTuning())}
            disabled={busy || !installed}
          >
            Initialize host tuning defaults
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Updates & maintenance">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Update check", () => runCheckUpdate())}
            disabled={busy || !installed}
          >
            Check for updates
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Update", () => runApplyUpdate())}
            disabled={busy || !installed}
          >
            Install latest release
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Refresh paths", () => runRefreshConfig())}
            disabled={busy || !installed}
          >
            Regenerate .env from detected paths
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              if (!removeConfirm) {
                setRemoveConfirm(true);
                setLog(
                  "Confirm: tap again to remove ALL games (keeps Desktop + Big Picture only)."
                );
                return;
              }
              setRemoveConfirm(false);
              runAction("Remove games", () => runRemove());
            }}
            disabled={busy || !installed}
          >
            {removeConfirm
              ? "Confirm remove all games"
              : "Remove all games (stock apps only)"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {log ? (
        <PanelSection title="Log">
          <PanelSectionRow>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                fontSize: "0.82em",
                maxHeight: "40vh",
                overflow: "auto",
              }}
            >
              {log}
            </pre>
          </PanelSectionRow>
        </PanelSection>
      ) : null}
    </>
  );
}

export default definePlugin(() => ({
  name: "GameSphere Companion Tool",
  titleView: (
    <div className={staticClasses.Title}>GameSphere Companion Tool</div>
  ),
  content: <Content />,
  icon: <FaSatelliteDish />,
  onDismount() {},
}));
