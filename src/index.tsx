import { useEffect, useState } from "react";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, ToggleField, Navigation, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";

type Status = { ready: boolean; busy: boolean; setting_up: boolean; phase: string; message: string };
type Game = { id: string; name: string; installed: boolean };
const getStatus = callable<[], Status>("status");
const scanGames = callable<[], Game[]>("scan");
const setup = callable<[consent: boolean], string>("setup");
const cancelSetup = callable<[], string>("cancel_setup");
const install = callable<[key: string], string>("install");
const restore = callable<[key: string], string>("restore");

function Content() {
  const [status, setStatus] = useState<Status>();
  const [games, setGames] = useState<Game[]>([]);
  const [selected, setSelected] = useState("");
  const [consent, setConsent] = useState(false);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [scanned, setScanned] = useState(false);
  const game = games.find(g => g.id === selected);
  const busy = working || status?.busy === true;

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
    return () => { mounted = false; clearInterval(timer); };
  }, []);

  const scan = async () => {
    const result = await scanGames();
    setGames(result); setScanned(true);
    setSelected(current => result.some(g => g.id === current) ? current : result[0]?.id ?? "");
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
  const note = (text: string) => <PanelSectionRow><div style={{ fontSize: 13, lineHeight: 1.5, opacity: 0.85, overflowWrap: "anywhere" }}>{text}</div></PanelSectionRow>;

  return <>
    <PanelSection title="Set up HelixSR">
      {note(status?.ready ? "HelixSR is ready." : status?.message || "Set up once, then install for each game.")}
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
      {games.length > 0 && <PanelSectionRow><DropdownItem label="Game" rgOptions={games.map(g => ({ data: g.id, label: `${g.name}${g.installed ? " · managed" : ""}` }))} selectedOption={selected} disabled={busy} onChange={o => setSelected(String(o.data))}/></PanelSectionRow>}
      {game && <>
        {game.installed ? <>
          {note("HelixSR is managed for this game. Restore also recovers an interrupted installation.")}
          <PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={() => void action(async () => { const r = await restore(game.id); await scan(); return r; })}>Restore original files</ButtonItem></PanelSectionRow>
        </> : <PanelSectionRow><ButtonItem layout="below" disabled={busy || !status?.ready} onClick={() => void action(async () => { const r = await install(game.id); await scan(); return r; })}>Install HelixSR</ButtonItem></PanelSectionRow>}
        {note("After installation, launch normally and select AMD FSR in the game's graphics settings.")}
      </>}
    </PanelSection>
    {message && <PanelSection title="Result">{note(message)}</PanelSection>}
  </>;
}

function Icon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M6 3c0 7 12 11 12 18M18 3C18 10 6 14 6 21M7 5h10M9 9h6M9 15h6M7 19h10"/></svg>;
}
export default definePlugin(() => ({ name: "Helix Deck", titleView: <div className={staticClasses.Title}>Helix Deck</div>, content: <Content/>, icon: <Icon/> }));
