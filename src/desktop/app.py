# src/desktop/app.py
"""
Aplicación de escritorio (Flet) para el Facebook Comment Monitor.

Reutiliza la lógica de negocio existente sin pasar por HTTP:
  - src.init.main          -> ejecuta el scraping completo (one-click)
  - el CSV generado por DataStorage se usa para poblar la tabla de comentarios.

Features de UI: catálogo de campañas, búsqueda/filtro, paginación, progreso en
vivo del scraping, config persistente, exportar a Excel y modo oscuro.
"""
import os
import csv
import json
import math
import threading
import logging
from typing import List, Dict, Optional

import flet as ft

from src.init import main as run_scraping
from src.storage.sheets import get_spreadsheet_url

logger = logging.getLogger(__name__)

# Mismo valor por defecto que usa src/init.py para el directorio de logs/CSV
LOG_DIR = os.getenv("LOG_DIR", "facebook_monitor_logs")
SHEETS_CREDS_FILE = os.getenv("GOOGLE_SHEETS_CREDS_FILE", "credentials.json")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".fb_monitor_config.json")
PAGE_SIZE = 100  # comentarios por página

CSV_FIELDS = [
    "comment_id", "user_id", "user_name",
    "created_time", "message", "has_attachment", "detected_time",
]

# Catálogo de campañas: 3 columnas -> datos de scraping.
# La "campaña" se identifica por el nombre de la hoja de Google Sheets (sheet_name).
CATALOG_FIELDS = ["post_id", "sheet_name", "worksheet_name"]
# Alias aceptados al cargar (encabezados tolerantes a variantes).
CATALOG_ALIASES = {
    "post_id": ("post_id", "postid", "post", "id", "id_post", "id_del_post"),
    "sheet_name": ("sheet_name", "hoja", "sheet", "nombre_hoja", "nombre_de_la_hoja",
                   "google_sheets", "campania", "campaña"),
    "worksheet_name": ("worksheet_name", "pestaña", "pestana", "worksheet",
                       "nombre_pestana", "nombre_de_la_pestaña"),
}


def load_catalog_csv(path: str) -> List[Dict[str, str]]:
    """Carga el catálogo de campañas, mapeando encabezados a las claves canónicas."""
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Mapa header_real(normalizado) -> clave canónica
        header_map = {}
        for h in (reader.fieldnames or []):
            norm = (h or "").strip().lower()
            for canonical, aliases in CATALOG_ALIASES.items():
                if norm in aliases:
                    header_map[h] = canonical
                    break
        rows = []
        for raw in reader:
            row = {c: "" for c in CATALOG_FIELDS}
            for real_h, canonical in header_map.items():
                row[canonical] = (raw.get(real_h) or "").strip()
            if any(row[c] for c in CATALOG_FIELDS):
                rows.append(row)
        return rows


def save_catalog_csv(path: str, rows: List[Dict[str, str]]) -> None:
    """Escribe el catálogo de campañas con los encabezados canónicos."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in CATALOG_FIELDS})


def _csv_path_for(post_id: str) -> str:
    return os.path.join(LOG_DIR, f"comments_{post_id}.csv")


def facebook_comment_url(comment_id: str) -> str:
    """Construye la URL del comentario en Facebook a partir de su id."""
    return f"https://www.facebook.com/{comment_id}"


def load_comments_from_csv(post_id: str) -> List[Dict[str, str]]:
    """Carga los comentarios scrapeados desde el CSV generado por DataStorage."""
    path = _csv_path_for(post_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:  # pragma: no cover - lectura defensiva
        logger.error(f"No se pudo leer el CSV {path}: {e}")
        return []


def load_config() -> Dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: Dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:  # pragma: no cover
        logger.warning(f"No se pudo guardar la configuración: {e}")


def export_to_xlsx(rows: List[Dict[str, str]], path: str) -> None:
    """Escribe los comentarios dados a un archivo .xlsx."""
    from openpyxl import Workbook  # import perezoso
    wb = Workbook()
    ws = wb.active
    ws.title = "Comentarios"
    ws.append(CSV_FIELDS)
    for c in rows:
        ws.append([c.get(k, "") for k in CSV_FIELDS])
    wb.save(path)


def main(page: ft.Page):
    config = load_config()

    page.title = "RedPetroil · Facebook Comment Monitor"
    page.theme_mode = ft.ThemeMode.DARK if config.get("dark_mode") else ft.ThemeMode.LIGHT
    page.padding = 20
    page.window.width = 1000
    page.window.height = 720
    page.window.min_width = 820
    page.window.min_height = 680
    page.scroll = None

    # ---- Estado ----
    current_post_id = {"value": ""}
    state = {"all": [], "filtered": [], "page": 0}  # datos cargados / filtrados / página actual
    selected_image_url = {"value": None}
    catalog = {"rows": [], "path": config.get("catalog_path")}  # campañas cargadas + ruta del CSV

    # ---- Controles de entrada (prefijados desde la config) ----
    # Los campos arrancan en blanco; se llenan al elegir una campaña del catálogo
    # o manualmente. (No se autocompletan desde la config para no confundir.)
    post_id_field = ft.TextField(label="Post ID", width=260, dense=True)
    sheet_field = ft.TextField(label="Nombre de la hoja (Google Sheets)", width=300, dense=True)
    worksheet_field = ft.TextField(label="Nombre de la pestaña", width=240, dense=True)

    # Catálogo: desplegable buscable (por nombre o id) que autocompleta los 3 campos.
    station_dropdown = ft.Dropdown(
        label="Catálogo de campañas", expand=True,
        editable=True, enable_filter=True, dense=True,
    )

    status_text = ft.Text("Listo.", color=ft.Colors.GREY)
    progress = ft.ProgressRing(width=18, height=18, visible=False)

    search_field = ft.TextField(
        label="Buscar (usuario, mensaje o fecha)", dense=True, expand=True,
        prefix_icon=ft.Icons.SEARCH,
    )

    # ---- Lista de comentarios + paginación ----
    comments_list = ft.Column(expand=True, adaptive=True, scroll=ft.ScrollMode.ALWAYS, spacing=0)
    page_label = ft.Text("—", size=12, color=ft.Colors.GREY)
    prev_btn = ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip="Página anterior", disabled=True)
    next_btn = ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip="Página siguiente", disabled=True)
    export_btn = ft.OutlinedButton("Exportar a Excel", icon=ft.Icons.DOWNLOAD)

    # ---- Visor de imagen ----
    image_view = ft.Image(
        width=320, height=320, fit=ft.ImageFit.CONTAIN,
        error_content=ft.Text("No se pudo cargar la imagen"),
    )
    image_placeholder = ft.Container(
        content=ft.Text("Selecciona un comentario con adjunto", color=ft.Colors.GREY),
        width=320, height=320, alignment=ft.alignment.center,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE), border_radius=8,
    )
    image_container = ft.Container(content=image_placeholder)

    # ---- Persistencia de config ----
    def save_current_config():
        save_config({
            "post_id": post_id_field.value.strip(),
            "sheet_name": sheet_field.value.strip(),
            "worksheet_name": worksheet_field.value.strip(),
            "dark_mode": page.theme_mode == ft.ThemeMode.DARK,
            "catalog_path": catalog["path"],
        })

    # ---- Helpers de UI ----
    def set_status(msg: str, busy: bool = False, color=ft.Colors.GREY):
        status_text.value = msg
        status_text.color = color
        progress.visible = busy
        page.update()

    def show_image(url: Optional[str]):
        selected_image_url["value"] = url
        if url and url not in ("No", "", None):
            image_view.src = url
            image_container.content = image_view
        else:
            image_container.content = image_placeholder
        page.update()

    def build_row(index: int, c: Dict[str, str]) -> ft.Control:
        attachment = c.get("has_attachment", "No")
        has_img = attachment not in ("No", "", None)
        comment_id = c.get("comment_id", "")
        message = (c.get("message", "") or "").strip() or "(sin texto)"

        trailing_controls = []
        if has_img:
            trailing_controls.append(ft.Icon(ft.Icons.IMAGE, color=ft.Colors.BLUE_400, tooltip="Tiene adjunto"))
        if comment_id:
            trailing_controls.append(
                ft.IconButton(
                    ft.Icons.OPEN_IN_NEW,
                    tooltip="Abrir comentario en Facebook",
                    on_click=lambda e, cid=comment_id: page.launch_url(facebook_comment_url(cid)),
                )
            )

        tile = ft.ListTile(
            leading=ft.Container(
                width=44, alignment=ft.alignment.center,
                content=ft.Text(f"#{index}", weight=ft.FontWeight.BOLD, color=ft.Colors.GREY),
            ),
            title=ft.Text(c.get("user_name", "—"), weight=ft.FontWeight.W_600),
            subtitle=ft.Text(f"{message[:90]}\n{c.get('created_time', '—')}", size=12, color=ft.Colors.GREY),
            trailing=ft.Row(trailing_controls, tight=True, spacing=0) if trailing_controls else None,
            on_click=(lambda e, u=attachment: show_image(u)) if has_img else None,
            dense=True,
        )
        return ft.Container(
            content=tile,
            border=ft.border.only(bottom=ft.border.BorderSide(1, ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE))),
        )

    # ---- Búsqueda + paginación + render ----
    def render_page():
        filtered = state["filtered"]
        total = len(filtered)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        state["page"] = max(0, min(state["page"], pages - 1))
        start = state["page"] * PAGE_SIZE
        chunk = filtered[start:start + PAGE_SIZE]
        comments_list.controls = [build_row(start + i + 1, c) for i, c in enumerate(chunk)]
        page_label.value = f"Página {state['page'] + 1} de {pages}  ·  {total} comentario(s)"
        prev_btn.disabled = state["page"] <= 0
        next_btn.disabled = state["page"] >= pages - 1
        page.update()

    def apply_filter(_=None):
        q = (search_field.value or "").strip().lower()
        if not q:
            state["filtered"] = state["all"]
        else:
            def match(c):
                return any(q in (c.get(k, "") or "").lower() for k in ("user_name", "message", "created_time"))
            state["filtered"] = [c for c in state["all"] if match(c)]
        state["page"] = 0
        render_page()

    def load_into_view(post_id: str):
        state["all"] = load_comments_from_csv(post_id)
        apply_filter()
        set_status(f"{len(state['all'])} comentario(s) con adjunto cargados.", busy=False)

    search_field.on_change = apply_filter
    prev_btn.on_click = lambda e: (state.update(page=state["page"] - 1), render_page())
    next_btn.on_click = lambda e: (state.update(page=state["page"] + 1), render_page())

    # ---- Acciones ----
    def do_scraping():
        post_id = post_id_field.value.strip()
        sheet = sheet_field.value.strip()
        worksheet = worksheet_field.value.strip()
        if not post_id or not sheet or not worksheet:
            set_status("Completa Post ID, hoja y pestaña.", busy=False, color=ft.Colors.RED)
            return

        current_post_id["value"] = post_id
        save_current_config()
        scrape_btn.disabled = True
        set_status("Scrapeando comentarios… esto puede tardar.", busy=True, color=ft.Colors.BLUE)

        stop_evt = threading.Event()

        def poller():
            # Progreso en vivo: cuenta filas del CSV que se va escribiendo.
            while not stop_evt.wait(2):
                n = len(load_comments_from_csv(post_id))
                set_status(f"Scrapeando… {n} comentario(s) detectados.", busy=True, color=ft.Colors.BLUE)

        def worker():
            poll = threading.Thread(target=poller, daemon=True)
            poll.start()
            try:
                result = run_scraping(post_id, sheet, worksheet, "one-click")
                stop_evt.set()
                if isinstance(result, str) and result.lower().startswith("error"):
                    set_status(result, busy=False, color=ft.Colors.RED)
                else:
                    load_into_view(post_id)
            except Exception as e:
                stop_evt.set()
                logger.exception("Error durante el scraping")
                set_status(f"Error: {e}", busy=False, color=ft.Colors.RED)
            finally:
                stop_evt.set()
                scrape_btn.disabled = False
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    def do_refresh(e):
        pid = post_id_field.value.strip() or current_post_id["value"]
        if not pid:
            set_status("Primero indica un Post ID.", busy=False, color=ft.Colors.RED)
            return
        current_post_id["value"] = pid
        save_current_config()
        load_into_view(pid)

    # ---- Catálogo de campañas ----
    def _campaign_label(r: Dict[str, str]) -> str:
        # La campaña se identifica por el nombre de la hoja de Google Sheets.
        hoja = (r.get("sheet_name") or "").strip()
        ws = (r.get("worksheet_name") or "").strip()
        if hoja and ws:
            return f"{hoja} — {ws}"
        return hoja or (r.get("post_id") or "").strip() or "(sin nombre)"

    def rebuild_catalog_dropdown(selected_index: Optional[int] = None):
        # Clave interna = índice de fila (único aunque falte/repita el id de campaña).
        station_dropdown.options = [
            ft.dropdown.Option(key=str(i), text=_campaign_label(r))
            for i, r in enumerate(catalog["rows"])
        ]
        if selected_index is not None and 0 <= selected_index < len(catalog["rows"]):
            station_dropdown.value = str(selected_index)
        page.update()

    def _load_catalog_from_path(path: str):
        try:
            catalog["rows"] = load_catalog_csv(path)
            catalog["path"] = path
            rebuild_catalog_dropdown()
            save_current_config()
            set_status(f"Catálogo cargado: {len(catalog['rows'])} campaña(s).", busy=False, color=ft.Colors.GREEN)
        except Exception as ex:
            logger.exception("Error cargando catálogo")
            set_status(f"No se pudo cargar el catálogo: {ex}", busy=False, color=ft.Colors.RED)

    def on_catalog_picked(e: ft.FilePickerResultEvent):
        if e.files:
            _load_catalog_from_path(e.files[0].path)

    catalog_picker = ft.FilePicker(on_result=on_catalog_picked)
    page.overlay.append(catalog_picker)

    def do_load_catalog(e):
        catalog_picker.pick_files(
            dialog_title="Selecciona el CSV del catálogo de campañas",
            allowed_extensions=["csv"], allow_multiple=False,
        )

    def on_campaign_select(e):
        try:
            idx = int(station_dropdown.value)
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(catalog["rows"])):
            return
        row = catalog["rows"][idx]
        post_id_field.value = row["post_id"]
        sheet_field.value = row["sheet_name"]
        worksheet_field.value = row["worksheet_name"]
        set_status(f"Cargada campaña '{_campaign_label(row)}'.", busy=False, color=ft.Colors.GREEN)

    station_dropdown.on_change = on_campaign_select

    # --- Guardar nueva campaña (diálogo): pide las 3 columnas del catálogo ---
    dlg_post = ft.TextField(label="Post ID a scrapear", dense=True)
    dlg_sheet = ft.TextField(label="Nombre de la hoja (Google Sheets)", dense=True)
    dlg_ws = ft.TextField(label="Nombre de la pestaña", dense=True)
    dlg_info = ft.Text("", size=12, color=ft.Colors.GREY)

    def close_dialog(e=None):
        page.close(save_dialog)

    def _persist_catalog():
        if catalog["path"]:
            save_catalog_csv(catalog["path"], catalog["rows"])
            return True
        # Sin ruta aún: pedir dónde crear el catálogo.
        catalog_save_picker.save_file(
            dialog_title="Crear archivo de catálogo", file_name="catalogo_campanias.csv",
            allowed_extensions=["csv"],
        )
        return False

    def confirm_save_campaign(e):
        post = dlg_post.value.strip()
        sheet = dlg_sheet.value.strip()
        ws = dlg_ws.value.strip()
        if not (post and sheet and ws):
            dlg_info.value = "Los 3 campos son obligatorios."
            dlg_info.color = ft.Colors.RED
            page.update()
            return
        new_row = {"post_id": post, "sheet_name": sheet, "worksheet_name": ws}
        # Append, evitando duplicados exactos.
        existing_idx = next((i for i, r in enumerate(catalog["rows"])
                             if r["post_id"] == post and r["sheet_name"] == sheet
                             and r["worksheet_name"] == ws), None)
        if existing_idx is not None:
            sel = existing_idx
        else:
            catalog["rows"].append(new_row)
            sel = len(catalog["rows"]) - 1
        catalog["sel_index"] = sel
        close_dialog()
        if _persist_catalog():
            rebuild_catalog_dropdown(selected_index=sel)
            save_current_config()
            set_status(f"Campaña '{sheet}' guardada en el catálogo.", busy=False, color=ft.Colors.GREEN)

    save_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Guardar campaña"),
        content=ft.Column([dlg_post, dlg_sheet, dlg_ws, dlg_info], tight=True, width=420, spacing=12),
        actions=[
            ft.TextButton("Cancelar", on_click=close_dialog),
            ft.FilledButton("Guardar", on_click=confirm_save_campaign),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def on_catalog_save_picked(e: ft.FilePickerResultEvent):
        if not e.path:
            return
        path = e.path if e.path.lower().endswith(".csv") else e.path + ".csv"
        try:
            save_catalog_csv(path, catalog["rows"])
            catalog["path"] = path
            rebuild_catalog_dropdown(selected_index=catalog.get("sel_index"))
            save_current_config()
            set_status(f"Catálogo guardado en {path}.", busy=False, color=ft.Colors.GREEN)
        except Exception as ex:
            logger.exception("Error guardando catálogo")
            set_status(f"No se pudo guardar el catálogo: {ex}", busy=False, color=ft.Colors.RED)

    catalog_save_picker = ft.FilePicker(on_result=on_catalog_save_picked)
    page.overlay.append(catalog_save_picker)

    def do_save_campaign(e):
        # Precarga los 3 campos del diálogo desde lo que haya en los campos principales
        # (editables antes de guardar).
        dlg_post.value = post_id_field.value.strip()
        dlg_sheet.value = sheet_field.value.strip()
        dlg_ws.value = worksheet_field.value.strip()
        dlg_info.value = "Se hará append de esta campaña al CSV del catálogo."
        dlg_info.color = ft.Colors.GREY
        page.open(save_dialog)

    def do_open_sheets(e):
        sheet = sheet_field.value.strip()
        if not sheet:
            set_status("Indica el nombre de la hoja de Google Sheets.", busy=False, color=ft.Colors.RED)
            return
        set_status("Abriendo Google Sheets…", busy=True, color=ft.Colors.BLUE)

        def worker():
            try:
                url = get_spreadsheet_url(SHEETS_CREDS_FILE, sheet)
                page.launch_url(url)
                set_status("Google Sheets abierto en el navegador.", busy=False, color=ft.Colors.GREEN)
            except Exception as ex:
                logger.exception("Error abriendo Google Sheets")
                set_status(f"No se pudo abrir Sheets: {ex}", busy=False, color=ft.Colors.RED)
            finally:
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    # ---- Exportar a Excel ----
    def on_export_result(e: ft.FilePickerResultEvent):
        if not e.path:
            return
        path = e.path if e.path.lower().endswith(".xlsx") else e.path + ".xlsx"
        try:
            export_to_xlsx(state["filtered"], path)
            set_status(f"Exportados {len(state['filtered'])} comentario(s) a {path}", busy=False, color=ft.Colors.GREEN)
        except Exception as ex:
            logger.exception("Error exportando a Excel")
            set_status(f"No se pudo exportar: {ex}", busy=False, color=ft.Colors.RED)

    file_picker = ft.FilePicker(on_result=on_export_result)
    page.overlay.append(file_picker)

    def do_export(e):
        if not state["filtered"]:
            set_status("No hay comentarios para exportar.", busy=False, color=ft.Colors.RED)
            return
        file_picker.save_file(
            dialog_title="Guardar comentarios como Excel",
            file_name="comentarios.xlsx", allowed_extensions=["xlsx"],
        )

    export_btn.on_click = do_export

    # ---- Modo oscuro ----
    def on_theme_change(e):
        page.theme_mode = ft.ThemeMode.DARK if e.control.value else ft.ThemeMode.LIGHT
        save_current_config()
        page.update()

    theme_switch = ft.Switch(label="Modo oscuro", value=config.get("dark_mode", False), on_change=on_theme_change)

    # ---- Botones principales ----
    scrape_btn = ft.FilledButton("Iniciar scraping", icon=ft.Icons.PLAY_ARROW, on_click=lambda e: do_scraping())
    refresh_btn = ft.OutlinedButton("Cargar guardados", icon=ft.Icons.REFRESH, on_click=do_refresh)
    sheets_btn = ft.OutlinedButton("Abrir Google Sheets", icon=ft.Icons.TABLE_VIEW, on_click=do_open_sheets)
    load_catalog_btn = ft.OutlinedButton("Cargar catálogo", icon=ft.Icons.FOLDER_OPEN, on_click=do_load_catalog)
    save_campaign_btn = ft.OutlinedButton("Guardar campaña", icon=ft.Icons.SAVE, on_click=do_save_campaign)

    # ---- Layout ----
    page.add(
        ft.Row(
            [
                ft.Text("Facebook Comment Monitor", size=22, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                theme_switch,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        # Catálogo de campañas: seleccionar estación autocompleta los 3 campos.
        ft.Row([load_catalog_btn, station_dropdown, save_campaign_btn],
               vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
        ft.Row([post_id_field, sheet_field, worksheet_field], wrap=True),
        ft.Row([scrape_btn, refresh_btn, sheets_btn, progress, status_text],
               vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
        ft.Divider(),
        ft.Row(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row([ft.Text("Comentarios", weight=ft.FontWeight.BOLD), search_field],
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
                            ft.Row([prev_btn, page_label, next_btn, ft.Container(expand=True), export_btn],
                                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            comments_list,
                        ],
                        expand=True, spacing=8,
                    ),
                    expand=True, padding=10,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.2, ft.Colors.ON_SURFACE)), border_radius=8,
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("Adjunto", weight=ft.FontWeight.BOLD),
                            image_container,
                        ],
                        spacing=10, scroll=ft.ScrollMode.AUTO,
                    ),
                    width=360, padding=10,
                    border=ft.border.all(1, ft.Colors.with_opacity(0.2, ft.Colors.ON_SURFACE)), border_radius=8,
                ),
            ],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )

    # Carga inicial del catálogo guardado (si la ruta sigue existiendo).
    # Solo puebla el desplegable; no selecciona nada ni rellena los campos.
    if catalog["path"] and os.path.exists(catalog["path"]):
        _load_catalog_from_path(catalog["path"])


def run():
    ft.app(target=main)


if __name__ == "__main__":
    run()
