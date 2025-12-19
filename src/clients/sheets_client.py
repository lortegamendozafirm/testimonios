# src/clients/sheets_client.py
from typing import Dict, Any, List
from googleapiclient.errors import HttpError

from src.auth import build_sheets_client
from src.logging_conf import get_logger

logger = get_logger(__name__)

def update_row_status(spreadsheet_id: str, sheet_name: str, row_index: int, col_letter: str, value: str):
    """
    Actualiza una celda individual en Google Sheets.
    Usa tu cliente autenticado centralizado.
    """
    try:
        # Obtenemos el cliente cacheado de tu src.auth
        sheets = build_sheets_client()
        
        range_name = f"{sheet_name}!{col_letter}{row_index}"
        body = {'values': [[value]]}
        
        sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        
        # logger.debug(f"Celda actualizada: {range_name} -> {value}")

    except HttpError as e:
        logger.error(f"❌ Error de API de Sheets al escribir en {range_name}: {e}")
    except Exception as e:
        logger.error(f"❌ Error inesperado en update_row_status: {e}")

def update_transcription_result(
    spreadsheet_id: str, 
    sheet_name: str, 
    row_index: int, 
    data: Dict[str, Any]
):
    """
    Actualiza múltiples columnas de una fila en una sola operación (Batch).
    Ideal para escribir URL, Status, Duración y Motor al mismo tiempo.
    """
    try:
        sheets = build_sheets_client()
        
        # Preparamos la lista de cambios para batchUpdate
        data_to_write = []

        # Mapeo: (Nombre del campo en 'data' que tiene la LETRA columna, Valor a escribir)
        field_map = [
            ("transcript_doc_col", data.get("doc_url")),
            ("status_col", data.get("status")),
            ("engine_col", data.get("engine")),
            ("duration_col", f"{data.get('duration_seconds', 0):.1f}s" if data.get('duration_seconds') else None),
            # Para el servicio de testimonios:
            ("testimony_doc_col", data.get("output_doc_link")) 
        ]

        for col_key_name, val_to_write in field_map:
            # data[col_key_name] contiene la LETRA de la columna (ej: 'H') que viene del Request
            col_letter = data.get(col_key_name)
            
            if col_letter and val_to_write:
                data_to_write.append({
                    "range": f"{sheet_name}!{col_letter}{row_index}",
                    "values": [[val_to_write]]
                })

        if not data_to_write:
            return

        body = {
            "valueInputOption": "USER_ENTERED",
            "data": data_to_write
        }
        
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()
        
        logger.info(f"📊 Sheet actualizada (Batch) en fila {row_index} con {len(data_to_write)} campos.")

    except HttpError as e:
        logger.error(f"❌ Error Batch Update en Sheets: {e}")
    except Exception as e:
        logger.error(f"❌ Error general en update_transcription_result: {e}")