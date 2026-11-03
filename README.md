# Indkøb til Home Assistant (uofficiel)

En fælles indkøbsliste i Home Assistant, der kan fyldes via stregkodescanner, stemme eller app, og sendes samlet til nemlig.com. Planlagt: madplan og sammenligning af tilbud i 365discount, Netto og Meny.

> **Uofficiel.** nemlig.com har intet offentligt API. Integrationen bruger de samme kald som deres hjemmeside og kan holde op med at virke, hvis nemlig ændrer noget. Brug den på egen risiko og i overensstemmelse med nemligs vilkår.

## Sådan virker det

1. **Fyld listen.** Scan en stregkode (`indkob.add_by_barcode`), sig "tilføj mælk til indkøbslisten", eller skriv i to-do-listen. Står varen der allerede, tælles antallet op.
2. **Gennemgå listen** i HA's to-do-visning. Antal skrives foran navnet: `3 × Letmælk`.
3. **Send til nemlig** (`indkob.send_to_nemlig`). Hver vare matches til et nemlig-produkt og lægges i kurven med det rigtige antal, hvorefter den markeres som klaret.
4. **Valg af vare:** som standard vælges altid det bedste match fra nemlig automatisk. Varens beskrivelse viser, hvad der blev valgt. Er det forkert, så skriv det rigtige id i beskrivelsen, fx `nemlig: [701011]`. Dine egne valg huskes fast, automatiske valg gør ikke.

Automatisk valg kan slås fra under **Indstillinger → Enheder og tjenester → Indkøb → Konfigurer**. Så bliver usikre varer stående med en notifikation og forslag, som du vælger imellem. Findes der slet intet relevant på nemlig, bliver varen altid stående.

Stregkoder slås op i [Open Food Facts](https://world.openfoodfacts.org) for navn, mærke og mængde. Varens beskrivelse viser altid, hvilket nemlig-produkt den er koblet til.

## Installation via HACS

1. HACS → ⋮ → **Custom repositories** → `https://github.com/tuxn82/indkob-ha`, type **Integration**
2. Installér **Indkøb** og genstart Home Assistant
3. **Indstillinger → Enheder og tjenester → Tilføj integration → Indkøb**, log ind med din nemlig-konto

## Entiteter

| Entitet (engelsk HA) | Beskrivelse |
|---|---|
| `todo.indkob_shopping_list` | Indkøbslisten |
| `sensor.indkob_nemlig_basket_total` | nemlig-kurvens varer i alt |
| `sensor.indkob_nemlig_basket_incl_fees` | nemlig-kurven inkl. levering og gebyrer |
| `sensor.indkob_nemlig_products_in_basket` | Antal varer i nemlig-kurven |

Entitets-id'erne følger Home Assistants sprog, da de dannes ud fra navnene. Kører HA på dansk, hedder listen fx `todo.indkob_indkobsliste`.

## Dashboard-kort

Integrationen leverer to kort, der indlæses automatisk.

**Indkøbslisten med antal-knapper:**

```yaml
type: custom:indkob-list-card
entity: todo.indkob_shopping_list   # standard
show_send: true                      # vis "Send til nemlig"
```

Hver vare har − og +. Ved antal 1 bliver − til en skraldespand. Under navnet står det valgte nemlig-produkt. "Send til nemlig" kræver to tryk, så man ikke sender ved et uheld.

### Scan med telefonens kamera

Integrationen leverer et dashboard-kort, der bruger telefonens kamera:

```yaml
type: custom:indkob-scanner-card
continuous: true   # bliv ved med at scanne (standard)
quantity: 1        # antal pr. scanning
```

Tryk **Start kamera**, og hold stregkoden ind i billedet. Ved et fund bipper telefonen, vibrerer (i Home Assistant-appen) og viser et flueben med varens navn, og varen kommer på indkøbslisten. Samme stregkode tælles først igen, når den har været ude af billedet i 1,5 sekund: vil du have to af noget, så flyt varen væk og frem igen. Man kan også taste stregkoden.

Kameraet kræver, at Home Assistant åbnes via **HTTPS**. Virker kortet ikke i companion-appen, så giv appen adgang til kameraet i telefonens indstillinger, eller åbn HA i telefonens browser.

## Services

| Service | Formål |
|---|---|
| `indkob.add_by_barcode` | Stregkode → vare på listen (`barcode`, `quantity`) |
| `indkob.send_to_nemlig` | Læg åbne varer i nemlig-kurven (`dry_run`) |
| `indkob.resolve_item` | Kobl en vare til et nemlig-produkt-id (`item`, `product_id`) |
| `indkob.forget_match` | Glem en husket kobling (`key`: stregkode eller navn) |
| `indkob.search` | Søg på nemlig (response) |

Events: `indkob_item_added` efter hver scanning (navn, antal, om varen blev genkendt) og `indkob_sent_to_nemlig` efter hver afsendelse. Brug dem fx til at vise resultatet på en skærm ved scanneren.

### Eksempel: stregkodescanner med ESPHome

```yaml
automation:
  - alias: "Indkøb: scannet vare"
    triggers:
      - trigger: state
        entity_id: text_sensor.stregkodescanner
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.state | length >= 8 }}"
    actions:
      - action: indkob.add_by_barcode
        data:
          barcode: "{{ trigger.to_state.state }}"
```

### Eksempel: knap til "Send til nemlig"

```yaml
type: button
name: Send til nemlig
icon: mdi:cart-arrow-right
tap_action:
  action: perform-action
  perform_action: indkob.send_to_nemlig
```

Produkt-id for en vare står sidst i URL'en på nemlig.com, fx `.../letmaelk-1-5-701011` → `701011`.

## Test uden Home Assistant

```bash
pip install aiohttp
python3 tools/cli.py search "letmælk"
python3 tools/cli.py basket --raw
python3 tools/cli.py scan 5700426101217
```

## Kendte begrænsninger

- Ingen re-auth-flow endnu: skifter du adgangskode, skal integrationen fjernes og tilføjes igen.

## Køreplan

- v0.3: madplan (Mealie eller nemligs opskrifter) → ingredienser på listen
- v0.4: tilbud fra 365discount, Netto og Meny via eTilbudsavis, og de 3 billigste steder at handle listen
