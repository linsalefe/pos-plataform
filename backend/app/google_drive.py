import os
import httpx
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from datetime import datetime

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "..", "google-credentials.json")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_FOLDER_NAME = "Gravações CENAT"

_drive_service = None
_folder_id = None


def get_drive_service():
    global _drive_service
    if _drive_service:
        return _drive_service

    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES
    )
    _drive_service = build("drive", "v3", credentials=credentials)
    return _drive_service


def get_or_create_folder(folder_name: str, parent_id: str = None) -> str:
    """Busca ou cria uma pasta no Google Drive."""
    service = get_drive_service()

    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        file_metadata["parents"] = [parent_id]

    folder = service.files().create(body=file_metadata, fields="id").execute()
    return folder["id"]


def get_root_folder_id() -> str:
    """Retorna o ID da pasta raiz 'Gravações CENAT'."""
    global _folder_id
    if _folder_id:
        return _folder_id
    _folder_id = get_or_create_folder(DRIVE_FOLDER_NAME)
    return _folder_id


async def upload_recording_to_drive(
    recording_url: str,
    call_sid: str,
    from_number: str,
    to_number: str,
    user_name: str = "Desconhecido",
    duration: int = 0,
) -> str:
    """Baixa gravação da Twilio e faz upload ao Google Drive. Retorna o link."""
    # Baixar o áudio da Twilio
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            recording_url,
            auth=(account_sid, auth_token),
            follow_redirects=True,
        )
        if response.status_code != 200:
            print(f"❌ Erro ao baixar gravação: {response.status_code}")
            return ""

        audio_data = response.content

    # Organizar em subpasta por consultora
    root_folder_id = get_root_folder_id()
    subfolder_name = user_name if user_name != "Desconhecido" else "Geral"
    subfolder_id = get_or_create_folder(subfolder_name, root_folder_id)

    # Nome do arquivo
    now = datetime.now().strftime("%Y-%m-%d_%H%M")
    duration_min = f"{duration // 60}m{duration % 60:02d}s"
    file_name = f"{now}_{from_number}_para_{to_number}_{duration_min}.mp3"

    # Upload ao Drive
    service = get_drive_service()
    file_metadata = {
        "name": file_name,
        "parents": [subfolder_id],
    }
    media = MediaInMemoryUpload(audio_data, mimetype="audio/mpeg")

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    # Tornar acessível via link
    service.permissions().create(
        fileId=uploaded["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    drive_link = uploaded.get("webViewLink", "")
    print(f"☁️ Gravação enviada ao Drive: {drive_link}")
    return drive_link


def delete_old_recordings(days: int = 90):
    """Exclui gravações com mais de X dias do Google Drive."""
    from datetime import timedelta

    service = get_drive_service()
    root_folder_id = get_root_folder_id()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    query = (
        f"'{root_folder_id}' in parents or mimeType='audio/mpeg' "
        f"and createdTime < '{cutoff}' and trashed=false"
    )

    # Buscar em todas as subpastas
    subfolders = service.files().list(
        q=f"'{root_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)",
    ).execute().get("files", [])

    deleted_count = 0
    for folder in subfolders:
        files = service.files().list(
            q=f"'{folder['id']}' in parents and mimeType='audio/mpeg' and createdTime < '{cutoff}' and trashed=false",
            fields="files(id, name, createdTime)",
        ).execute().get("files", [])

        for f in files:
            try:
                service.files().delete(fileId=f["id"]).execute()
                deleted_count += 1
                print(f"🗑️ Deletado: {f['name']}")
            except Exception as e:
                print(f"❌ Erro ao deletar {f['name']}: {e}")

    print(f"🗑️ Total deletado: {deleted_count} gravações com +{days} dias")
    return deleted_count
