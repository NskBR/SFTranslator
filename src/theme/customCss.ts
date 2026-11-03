const selectors = new Set([".game-card", ".settings-panel", ".model-card", "aside nav button", ".page-heading h1", ".sidebar-overview", ".theme-tile"]);
const colors = new Set(["color", "background-color", "border-color"]);
const lengths = new Set(["border-radius", "letter-spacing", "font-size"]);

/** A deliberately small CSS subset: no URLs, at-rules, positioning or pseudo selectors. */
export function compileCustomCss(source: string): string {
  if (!source.trim()) return "";
  if (source.length > 8192 || /[\\@<>]|url\s*\(|var\s*\(|!important|expression\s*\(/i.test(source)) throw new Error("CSS contém recurso não permitido.");
  const rules: string[] = [];
  const pattern = /\s*([^{}]+)\{([^{}]*)\}\s*/gy;
  let cursor = 0;
  while (cursor < source.length) {
    pattern.lastIndex = cursor;
    const match = pattern.exec(source);
    if (!match || match.index !== cursor) throw new Error("Formato CSS inválido.");
    const selector = match[1].trim();
    if (!selectors.has(selector)) throw new Error(`Seletor não permitido: ${selector}`);
    const declarations = match[2].split(";").map(item => item.trim()).filter(Boolean).map(item => {
      const colon = item.indexOf(":");
      if (colon < 1) throw new Error("Declaração CSS inválida.");
      const property = item.slice(0, colon).trim().toLowerCase();
      const value = item.slice(colon + 1).trim();
      if (colors.has(property) && /^#[0-9a-f]{6}$/i.test(value)) return `${property}:${value}`;
      if (lengths.has(property) && /^(?:[0-9]|[1-3][0-9])(?:\.[0-9])?px$/.test(value)) return `${property}:${value}`;
      throw new Error(`Propriedade ou valor não permitido: ${property}`);
    });
    rules.push(`.shell ${selector}{${declarations.join(";")}}`);
    cursor = pattern.lastIndex;
  }
  return rules.join("\n");
}
