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
const initHostTuning = callable<[], RunResult>("init_host_tuning");

function Content() {
  const [dryRun, setDryRun] = useState(true);
  const [noRestart, setNoRestart] = useState(false);
  const [hostTuning, setHostTuning] = useState(true);
  const [verbose, setVerbose] = useState(false);
  const [bridgeOn, setBridgeOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");
  const [status, setStatus] = useState<Status | null>(null);

  const refreshStatus = useCallback(async () => {
    const s = await getStatus();
    setStatus(s);
    setBridgeOn(s.bridge_service === "active");
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
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const installed = status?.installed ?? false;
  const hostLabel = status?.paths?.GAMESPHERE_HOST_LABEL || status?.paths?.host_label || "";
  const appsPath = status?.paths?.sunshine_apps_json_path || "—";
  const linkMbps = status?.host_tuning?.link?.current_mbps;
  const sessions = status?.host_tuning?.sessions_count ?? 0;

  return (
    <>
      <PanelSection title="Status">
        <PanelSectionRow>
          <Field label="Import Tool">
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

      <PanelSection title="Sync Steam library">
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
            onClick={() => runAction("Remove games", () => runRemove())}
            disabled={busy || !installed}
          >
            Remove all games (stock apps only)
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
  title: <div className="gamesphere-import-title">GameSphere Import</div>,
  content: <Content />,
  icon: "https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main/assets/readme-screenshot.png",
  onDismount() {},
}));
