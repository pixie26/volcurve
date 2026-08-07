#!/usr/bin/env python3
from pathlib import Path
import re

path = Path.cwd() / "app/web/compare-builder.js"
if not path.exists():
    raise SystemExit("[ERROR] Run from the volcurve repo root.")

text = path.read_text(encoding="utf-8")
required = "VOLCURVE_LISTED_DATE_RACE_FIX_V1_8_1"
marker = "VOLCURVE_LISTED_DATE_KEYBOARD_FIX_V1_8_2"

if marker in text:
    raise SystemExit("[ERROR] v1.8.2 already appears to be applied.")
if required not in text:
    raise SystemExit("[ERROR] v1.8.1 race fix not found. Apply v1.8.1 first. No file written.")

def replace_function(source, name, replacement):
    pattern = r'(?ms)^  (?:async )?function ' + re.escape(name) + r'\([^)]*\) \{.*?(?=^  (?:async )?function |\Z)'
    updated, count = re.subn(pattern, lambda _m: replacement.rstrip() + "\n\n", source, count=1)
    if count != 1:
        raise SystemExit(f"[ERROR] function {name}: expected 1 match, found {count}. No file written.")
    return updated

text = replace_function(text, "bindIndicatorDiscovery", '  function bindIndicatorDiscovery() {\n    if (indicatorState.draft.maturityMode !== "listed") return;\n\n    const observation = $("indicatorObservationDate");\n    if (observation) {\n      const syncDateOnly = () => {\n        const nextDate = observation.value;\n        indicatorState.listedObservationDate = nextDate;\n        indicatorState.draft.expiry = "";\n        indicatorState.draft.absoluteStrike = "";\n      };\n\n      observation.addEventListener("keydown", (event) => {\n        if (/^[0-9]$/.test(event.key) || ["Backspace", "Delete"].includes(event.key)) {\n          indicatorState.listedDateTyping = true;\n        }\n        if (event.key === "Enter") {\n          event.preventDefault();\n          syncDateOnly();\n          indicatorState.listedDateTyping = false;\n          if (validIsoDate(observation.value)) loadIndicatorCoordinates(observation.value);\n        }\n      });\n\n      // While the user is typing into the native date control, only preserve the value.\n      // Do not re-render the whole indicator form: replacing the focused <input type=date>\n      // causes Chromium to jump between date segments and makes keyboard entry unusable.\n      observation.addEventListener("input", syncDateOnly);\n\n      observation.addEventListener("change", () => {\n        syncDateOnly();\n        if (!indicatorState.listedDateTyping && validIsoDate(observation.value)) {\n          loadIndicatorCoordinates(observation.value);\n        }\n      });\n\n      observation.addEventListener("blur", () => {\n        syncDateOnly();\n        const nextDate = observation.value;\n        indicatorState.listedDateTyping = false;\n        if (\n          validIsoDate(nextDate)\n          && (\n            indicatorState.discovery?.code !== indicatorState.draft.instrumentCode.trim()\n            || indicatorState.discovery?.date !== nextDate\n          )\n        ) {\n          loadIndicatorCoordinates(nextDate);\n        }\n      });\n    }\n\n    const expirySelect = $("indicatorListedExpiry");\n    expirySelect?.addEventListener("change", () => {\n      const expiry = expirySelect.value;\n      if (indicatorState.draft.strikeKind === "absolute") {\n        indicatorState.draft.absoluteStrike = "";\n        if (expiry) loadListedStrikes(expiry);\n      }\n    });\n\n    const code = indicatorState.draft.instrumentCode.trim();\n    const date = indicatorState.listedObservationDate\n      || observation?.value\n      || $("endDate")?.value\n      || isoDate(new Date());\n    indicatorState.listedObservationDate = date;\n\n    const discovery = indicatorState.discovery;\n    const matches = discovery\n      && discovery.code === code\n      && discovery.date === date;\n\n    if (!matches) {\n      queueMicrotask(() => {\n        if (\n          indicatorState.draft.maturityMode === "listed"\n          && indicatorState.draft.instrumentCode.trim() === code\n          && indicatorState.listedObservationDate === date\n          && !indicatorState.listedDateTyping\n        ) {\n          loadIndicatorCoordinates(date);\n        }\n      });\n      return;\n    }\n\n    if (\n      discovery.status === "ready"\n      && indicatorState.draft.strikeKind === "absolute"\n      && indicatorState.draft.expiry\n      && !(\n        discovery.strikeExpiry === indicatorState.draft.expiry\n        && ["loading", "ready", "error"].includes(discovery.strikeStatus)\n      )\n    ) {\n      const expiry = indicatorState.draft.expiry;\n      queueMicrotask(() => {\n        if (\n          indicatorState.draft.maturityMode === "listed"\n          && indicatorState.listedObservationDate === date\n          && indicatorState.draft.expiry === expiry\n          && !indicatorState.listedDateTyping\n        ) {\n          loadListedStrikes(expiry);\n        }\n      });\n    }\n  }')
text += "\n  // " + marker + "\n"

path.write_text(text, encoding="utf-8")

print("Updated: app/web/compare-builder.js")
print("Keyboard entry in Observation date no longer triggers a re-render while typing.")
print("Typed dates load on blur or Enter; calendar selections still load on change.")
print("Next: python -m pytest -q; restart; Ctrl+F5.")
