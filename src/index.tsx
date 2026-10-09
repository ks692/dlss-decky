import { useEffect, useState } from "react";
import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, SliderField, ToggleField, Navigation, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";

type Status = { ready: boolean; busy: boolean; setting_up: boolean; phase: string; message: string };
type Game = { id: string; name: string; installed: boolean; installed_version: string | null };
type Versions = { plugin: string; helixsr: string; ready: boolean };
type Running = { running: boolean; processes: string[] };
type SettingItem = { section: string; key: string; label: string; kind: string; options?: string[]; min?: number; max?: number; default: number | string; help: string };
type SettingsData = { schema: SettingItem[]; values: Record<string, Record<string, number | string>>; customized: boolean };
const getStatus = callable<[], Status>("status");
const scanGames = callable<[], Game[]>("scan");
const setup = callable<[consent: boolean], string>("setup");
const cancelSetup = callable<[], string>("cancel_setup");
const install = callable<[key: string], string>("install");
const restore = callable<[key: string], string>("restore");
const getVersions = callable<[], Versions>("versions");
const readSetupLog = callable<[lines: number], string>("setup_log");
const readGameLog = callable<[key: string, lines: number], string>("game_log");
const checkRunning = callable<[key: string], Running>("game_running");
const checkRunningGames = callable<[], string[]>("running_games");
const loadSettings = callable<[key: string], SettingsData>("get_settings");
const saveSettings = callable<[key: string, values: Record<string, Record<string, number | string>>], string>("set_settings");

function Content() {
  const [status, setStatus] = useState<Status>();
  const [games, setGames] = useState<Game[]>([]);
  const [selected, setSelected] = useState("");
  const [consent, setConsent] = useState(false);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [scanned, setScanned] = useState(false);
  const [versions, setVersions] = useState<Versions>();
  const [running, setRunning] = useState("");
  const [runningIds, setRunningIds] = useState<string[]>([]);
  const [setupLog, setSetupLog] = useState("");
  const [gameLog, setGameLog] = useState("");
  const [settings, setSettings] = useState<SettingsData>();
  const [draft, setDraft] = useState<Record<string, Record<string, number | string>>>({});
  const game = games.find(g => g.id === selected);
  const busy = working || status?.busy === true;
  const gameInstalled = game?.installed === true;

  useEffect(() => {
    let mounted = true;
    let pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try { const next = await getStatus(); if (mounted) setStatus(next); }
      catch (e) { if (mounted) setMessage(String(e)); }
      finally { pending = false; }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2500);
    void scanGames().then(result => {
      if (mounted) { setGames(result); setScanned(true); setSelected(result[0]?.id ?? ""); }
    }).catch(e => { if (mounted) setMessage(String(e)); });
    void checkRunningGames().then(ids => { if (mounted) setRunningIds(ids); }).catch(() => {});
    void getVersions().then(v => { if (mounted) setVersions(v); }).catch(() => {});
    return () => { mounted = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!selected) { setRunning(""); return; }
    let mounted = true;
    void checkRunning(selected)
      .then(r => { if (mounted) setRunning(r.running ? r.processes.join(", ") : ""); })
      .catch(() => { if (mounted) setRunning(""); });
    return () => { mounted = false; };
  }, [selected]);

  useEffect(() => {
    if (!gameInstalled || !game) { setSettings(undefined); setDraft({}); return; }
    let mounted = true;
    void loadSettings(game.id)
      .then(s => { if (mounted) { setSettings(s); setDraft(JSON.parse(JSON.stringify(s.values))); } })
      .catch(e => { if (mounted) setMessage(String(e)); });
    return () => { mounted = false; };
  }, [selected, gameInstalled]);

  const setDraftValue = (section: string, key: string, value: number | string) =>
    setDraft(d => ({ ...d, [section]: { ...(d[section] ?? {}), [key]: value } }));
  const resetDraft = () => {
    if (!settings) return;
    const next: Record<string, Record<string, number | string>> = {};
    for (const item of settings.schema) {
      next[item.section] = { ...(next[item.section] ?? {}), [item.key]: item.default };
    }
    setDraft(next);
  };

  const scan = async () => {
    const result = await scanGames();
    setGames(result); setScanned(true);
    setSelected(current => result.some(g => g.id === current) ? current : result[0]?.id ?? "");
    try { setRunningIds(await checkRunningGames()); } catch { /* keep previous */ }
  };
  const action = async (fn: () => Promise<string | void>) => {
    setWorking(true); setMessage("");
    try {
      const result = await fn();
      if (result) { setMessage(result); toaster.toast({ title: "Helix Deck", body: result }); }
      setStatus(await getStatus());
    } catch (e) { setMessage(String(e)); }
    finally { setWorking(false); }
  };
  const note = (text: string) => <PanelSectionRow><div style={{ fontSize: 13, lineHeight: 1.5, opacity: 0.85, overflowWrap: "anywhere", wordBreak: "break-word", minWidth: 0, maxWidth: "100%" }}>{text}</div></PanelSectionRow>;
  const sortedGames = [...games].sort((a, b) => {
    const rank = (g: Game) => runningIds.includes(g.id) ? 0 : 1;
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  });
  const gameRow = (g: Game) => {
    const isRunning = runningIds.includes(g.id);
    const isSelected = g.id === selected;
    const status = [isRunning ? "● running" : "", g.installed ? `managed${g.installed_version ? ` · HelixSR ${g.installed_version}` : ""}` : "not installed"].filter(Boolean).join(" · ");
    return <div key={g.id} style={isSelected ? { borderLeft: "3px solid #1a9fff", background: "rgba(255,255,255,0.07)", borderRadius: 4 } : { borderLeft: "3px solid transparent" }}>
      <Field focusable disabled={busy} onClick={() => setSelected(g.id)} bottomSeparator="none"
        label={<div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>{g.name}</div>}
        description={<div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, color: isRunning ? "#7fd67f" : undefined }}>{status}</div>} />
    </div>;
  };

  return <div style={{ maxWidth: "100%", overflowX: "clip" }}>
    <PanelSection title="Set up HelixSR">
      {note(status?.ready ? `HelixSR ${versions?.helixsr ?? ""} is ready.` : status?.message || "Set up once, then install for each game.")}
      {note(`Helix Deck ${versions?.plugin ?? ""} · HelixSR runtime ${versions?.helixsr ?? "unknown"}`)}
      {!status?.ready && !status?.setting_up && <>
        {note("Setup downloads HelixSR and its dependencies, then generates the network on this Deck. Internet and an installed Proton are required.")}
        <PanelSectionRow><ButtonItem layout="below" onClick={() => Navigation.NavigateToExternalWeb("https://github.com/lonewolf0622/HelixSR/blob/main/LICENSE")}>HelixSR license</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={() => Navigation.NavigateToExternalWeb("https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt")}>NVIDIA license</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ToggleField label="Accept upstream terms" description="Allow downloads and local network generation under these licenses." checked={consent} disabled={busy} onChange={setConsent}/></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy || !consent || !status} onClick={() => void action(() => setup(consent))}>{status?.phase === "error" ? "Retry setup" : "Set up HelixSR"}</ButtonItem></PanelSectionRow>
      </>}
      {status?.setting_up && <>
        {note("This can take several minutes. Keep the Deck awake.")}
        <PanelSectionRow><ButtonItem layout="below" disabled={working} onClick={() => void action(() => cancelSetup())}>Cancel setup</ButtonItem></PanelSectionRow>
      </>}
    </PanelSection>
    <PanelSection title="Your games">
      {note("DirectX 12 games with a separate FSR 3.1 DLL. Close the game before installing or restoring.")}
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void action(scan)}>Refresh games</ButtonItem></PanelSectionRow>
      {scanned && games.length === 0 && note("No eligible games found. Check that the game and its Steam library are installed and mounted.")}
      {games.length > 0 && <PanelSectionRow><div style={{ display: "flex", flexDirection: "column", gap: 2, maxHeight: 264, overflowY: "auto", minWidth: 0, width: "100%" }}>{sortedGames.map(gameRow)}</div></PanelSectionRow>}
      {running && note(`This game appears to be running (${running}). Close it before installing or restoring files.`)}
      {game && <>
        {game.installed ? <>
          {note("HelixSR is managed for this game. Restore also recovers an interrupted installation.")}
          <PanelSectionRow><ButtonItem layout="below" disabled={busy || !!running} onClick={() => void action(async () => { const r = await restore(game.id); await scan(); return r; })}>Restore original files</ButtonItem></PanelSectionRow>
        </> : <PanelSectionRow><ButtonItem layout="below" disabled={busy || !status?.ready || !!running} onClick={() => void action(async () => { const r = await install(game.id); await scan(); return r; })}>Install HelixSR</ButtonItem></PanelSectionRow>}
        {note("After installation, launch normally and select AMD FSR in the game's graphics settings.")}
      </>}
    </PanelSection>
    {gameInstalled && settings && <PanelSection title="HelixSR settings">
      {note(settings.customized ? "Custom settings are active for this game." : "Using HelixSR defaults. Changes apply the next time the game launches.")}
      {settings.schema.map(item => {
        const value = draft[item.section]?.[item.key] ?? item.default;
        return <PanelSectionRow key={`${item.section}.${item.key}`}>
          {item.kind === "choice" && item.options
            ? <DropdownItem label={item.label} description={item.help} rgOptions={item.options.map(o => ({ data: o, label: o }))} selectedOption={String(value)} disabled={busy || !!running} onChange={o => setDraftValue(item.section, item.key, String(o.data))}/>
            : <SliderField label={item.label} description={item.help} value={Math.round(Number(value) * 100)} min={0} max={100} step={5} disabled={busy || !!running} onChange={v => setDraftValue(item.section, item.key, Math.round(v) / 100)}/>}
        </PanelSectionRow>;
      })}
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !!running} onClick={() => void action(async () => {
        const r = await saveSettings(game.id, draft);
        const s = await loadSettings(game.id);
        setSettings(s); setDraft(JSON.parse(JSON.stringify(s.values)));
        return r;
      })}>Save settings</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem layout="below" disabled={busy || !!running} onClick={() => resetDraft()}>Reset to defaults</ButtonItem></PanelSectionRow>
    </PanelSection>}
    <PanelSection title="Diagnostics">
      {note("Setup log and the renderer's game log, newest entries last.")}
      <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void action(async () => { const t = await readSetupLog(120); setSetupLog(t || "(no setup log yet)"); })}>Show setup log</ButtonItem></PanelSectionRow>
      {game && <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void action(async () => { const t = await readGameLog(game.id, 120); setGameLog(t || "(no game log yet — launch the game with FSR selected)"); })}>Show game log</ButtonItem></PanelSectionRow>}
      {(setupLog || gameLog) && <PanelSectionRow><div style={{ fontFamily: "monospace", fontSize: 11, lineHeight: 1.4, maxHeight: 220, overflowY: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere", wordBreak: "break-all", minWidth: 0, maxWidth: "100%", opacity: 0.9 }}>{setupLog}{setupLog && gameLog ? "\n---\n" : ""}{gameLog}</div></PanelSectionRow>}
    </PanelSection>
    {message && <PanelSection title="Result">{note(message)}</PanelSection>}
  </div>;
}

function Icon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 3c0 7 12 11 12 18M18 3C18 10 6 14 6 21M7 5h10M9 9h6M9 15h6M7 19h10"/></svg>;
}
export default definePlugin(() => ({ name: "Helix Deck", titleView: <div className={staticClasses.Title}>Helix Deck</div>, content: <Content/>, icon: <Icon/> }));
