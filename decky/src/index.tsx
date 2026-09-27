import {
  definePlugin,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  ToggleField,
} from "@decky/ui";
import { callable } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

type Status = {
  installed: boolean;
  version?: string;
  paths?: Record<string, string>;
  host_tuning?: {
    enabled?: boolean;
    adapter?: string;
    sessions_count?: number;
    link?: { current_mbps?: number };
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
  };
};

type RunResult = { ok: boolean; output: string; banner?: string };

const getStatus = callable<[], Status>("get_status");
const runImport = callable<
  [boolean, boolean, boolean, boolean],
  RunResult
>("run_import");
const runHostTuningOnly = callable<[], RunResult>("run_host_tuning_only");
const runRemove = callable<[], RunResult>("run_remove");
const runRefreshConfig = callable<[], RunResult>("run_refresh_config");
const runCheckUpdate = callable<[], RunResult>("run_check_update");
const runApplyUpdate = callable<[], RunResult>("run_apply_update");
const setBridgeEnabled = callable<
  [boolean],
  { ok: boolean; output: string; state?: string }
>("set_bridge_enabled");
const setLibrarySyncEnabled = callable<
  [boolean],
  { ok: boolean; output: string; state?: string }
>("set_library_sync_enabled");
const runLibrarySyncNow = callable<[], RunResult>("run_library_sync_now");
const runSetupMic = callable<[], RunResult>("run_setup_mic");
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

function formatMicLabel(status: Status | null): string {
  const mic = status?.mic;
  if (!mic) return "…";
  if (mic.detail) return mic.detail;
  if (mic.pcMicReady || mic.pipewireSourcePresent) return "GameSphere Mic ready";
  return "Idle — appears when voice starts";
}

function Content() {
  const [dryRun, setDryRun] = useState(true);
  const [noRestart, setNoRestart] = useState(false);
  const [hostTuning, setHostTuning] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState(false);
  const [verbose, setVerbose] = useState(false);
  const [bridgeOn, setBridgeOn] = useState(false);
  const [autoSyncOn, setAutoSyncOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");
  const [status, setStatus] = useState<Status | null>(null);

  // A rejected callable (backend reload, missing binary) must surface as text
  // instead of an unhandled rejection that leaves the panel blank.
  const describeError = (err: unknown): string =>
    err instanceof Error ? err.message : String(err);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setStatus(s);
      setBridgeOn(s.bridge_service === "active");
      const timer = s.library_sync_timer || "";
      setAutoSyncOn(timer === "active" || timer === "waiting");
    } catch (err) {
      setLog(`Could not read Companion status: ${describeError(err)}`);
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
      setLog(
        result.banner ? `${result.banner}\n\n${text}` : text
      );
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

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const installed = status?.installed ?? false;
  const hostLabel = status?.paths?.GAMESPHERE_HOST_LABEL || status?.paths?.host_label || "";
  const appsPath = status?.paths?.sunshine_apps_json_path || "—";
  const linkMbps = status?.host_tuning?.link?.current_mbps;
  const sessions = status?.host_tuning?.sessions_count ?? 0;
  const mic = status?.mic;

  return (
    <>
      <PanelSection title="Status">
        <PanelSectionRow>
          <Field label="Companion Tool">
            {status === null
              ? "…"
              : installed
              ? status.version || "Installed"
              : "Not installed — run install-linux.sh"}
          </Field>
        </PanelSectionRow>
        {installed ? (
          <>
            <PanelSectionRow>
              <Field label="Host profile">{hostLabel || "linux"}</Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="apps.json">{appsPath}</Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Bridge (TCP 47998)">
                {status?.bridge_service || "unknown"}
                {status?.bridge_unit_installed ? "" : " — unit not installed yet"}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <Field label="Host tuning">
                {status?.host_tuning?.enabled ? "Enabled" : "Disabled"}
                {linkMbps ? ` · ${linkMbps} Mbps` : ""}
                {sessions ? ` · ${sessions} session(s) logged` : ""}
              </Field>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={refreshStatus} disabled={busy}>
                Refresh status
              </ButtonItem>
            </PanelSectionRow>
          </>
        ) : null}
      </PanelSection>

      <PanelSection title="Mic (GameSphere Mic)">
        <PanelSectionRow>
          <Field label="Status">{formatMicLabel(status)}</Field>
        </PanelSectionRow>
        {installed && mic ? (
          <>
            <PanelSectionRow>
              <Field label="PipeWire source">
                {mic.pipewireSourcePresent === true
                  ? "Present"
                  : mic.pipewireSourcePresent === false
                  ? "Missing"
                  : "—"}
                {mic.voiceRunning ? " · voice running" : ""}
                {typeof mic.clients === "number" && mic.clients > 0
                  ? ` · ${mic.clients} client(s)`
                  : ""}
              </Field>
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
          </>
        ) : null}
      </PanelSection>

      <PanelSection title="Sync Steam library">
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
          <ButtonItem
            layout="below"
            onClick={() => runAction("Auto-sync", () => runLibrarySyncNow())}
            disabled={busy || !installed}
          >
            Sync now (no Sunshine restart)
          </ButtonItem>
        </PanelSectionRow>
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
          <ToggleField
            label="Verbose log"
            checked={verbose}
            onChange={setVerbose}
          />
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
              ? "Preview import"
              : "Import Steam + shortcuts"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Host tuning">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Host tuning init", () => initHostTuning())}
            disabled={busy || !installed}
          >
            Initialize host tuning (enable all)
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => runAction("Host tuning", () => runHostTuningOnly())}
            disabled={busy || !installed}
          >
            Apply host tuning only
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="GameSphere bridge service (TCP 47998)"
            checked={bridgeOn}
            onChange={onBridgeToggle}
            disabled={busy || !installed}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Maintenance">
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
            {removeConfirm ? "Confirm remove all games" : "Remove all games (stock apps only)"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {log ? (
        <PanelSection title="Log">
          <PanelSectionRow>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.82em", maxHeight: "40vh", overflow: "auto" }}>
              {log}
            </pre>
          </PanelSectionRow>
        </PanelSection>
      ) : null}
    </>
  );
}

export default definePlugin(() => ({
  title: <div className="gamesphere-companion-title">GameSphere Companion</div>,
  content: <Content />,
  icon: "https://raw.githubusercontent.com/trevlars/GameSphere-Companion-Tool/main/assets/readme-screenshot.png",
  onDismount() {},
}));
