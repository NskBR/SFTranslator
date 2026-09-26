import { useEffect, useRef, useState } from "react";
import { ChevronDown, Search } from "lucide-react";

const LANGUAGE_COUNTRIES:Record<string,string>={ar:"SA",az:"AZ",bg:"BG",bn:"BD",ca:"ES",cs:"CZ",da:"DK",de:"DE",el:"GR",en:"US",es:"ES",et:"EE",eu:"ES",fa:"IR",fi:"FI",fr:"FR",ga:"IE",gl:"ES",he:"IL",hi:"IN",hu:"HU",id:"ID",it:"IT",ja:"JP",ko:"KR",ky:"KG",lt:"LT",lv:"LV",ms:"MY",nb:"NO",nl:"NL",pb:"BR",pl:"PL",pt:"PT",ro:"RO",ru:"RU",sk:"SK",sl:"SI",sq:"AL",sv:"SE",sw:"KE",th:"TH",tl:"PH",tr:"TR",uk:"UA",ur:"PK",vi:"VN",zh:"CN",zt:"TW"};
export function LanguageFlag({code,name}:{code:string;name:string}) {
  const country=LANGUAGE_COUNTRIES[code.toLowerCase()];
  return country
    ? <span className={`flag:${country} flag-icon`} role="img" aria-label={name} title={name}/>
    : <span className="flag-code" role="img" aria-label={name} title={name}>{code.toUpperCase()}</span>;
}

type SelectOption = { value: string; label: string };
export function UiSelect({ value, options, onChange, ariaLabel }: { value: string; options: SelectOption[]; onChange: (value: string) => void; ariaLabel: string }) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const selectRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const selected = options.find(option => option.value === value);
  const normalizedQuery = query.trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
  const filteredOptions = options.filter(option => `${option.label} ${option.value}`.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().includes(normalizedQuery));
  useEffect(() => {
    const close = (event: MouseEvent) => { if (!selectRef.current?.contains(event.target as Node)) setExpanded(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setExpanded(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, []);
  useEffect(() => {
    if (expanded) searchRef.current?.focus();
    else setQuery("");
  }, [expanded]);
  return <div className={`ui-select ${expanded ? "open" : ""}`} ref={selectRef}>
    <button type="button" className="ui-select-trigger" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={expanded} onClick={() => setExpanded(open => !open)}><span>{selected?.label || "Selecione"}</span><ChevronDown size={16}/></button>
    {expanded && <div className="ui-select-menu" role="listbox" aria-label={ariaLabel}><label className="ui-select-search"><Search size={14}/><input ref={searchRef} value={query} onChange={event => setQuery(event.target.value)} placeholder="Digite para buscar" aria-label={`Buscar em ${ariaLabel}`}/></label><div className="ui-select-options">{filteredOptions.length ? filteredOptions.map(option => <button type="button" key={option.value} role="option" aria-selected={option.value === value} className={option.value === value ? "selected" : ""} onClick={() => { onChange(option.value); setExpanded(false); }}><span>{option.label}</span>{option.value === value && <i>Selecionado</i>}</button>) : <p>Nenhum idioma encontrado.</p>}</div></div>}
  </div>;
}
