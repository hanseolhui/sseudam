"""Validate an installed Windows upgrade using only disposable Actions fixtures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request
import wave


TABLES = ("classes", "students", "recordings", "notes", "drafts")
PRESERVED = ("backup_folder", "backup_audio", "backup_folder_last", "backup_audio_last",
             "teacher_name", "sheets_auto", "drive_backup", "auto_update", "text_sync")


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request("http://127.0.0.1:%s%s" % (os.environ["SETEUK_PORT"], path),
                                     data=data, headers={"X-Seteuk": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(data):
    with sqlite3.connect(str(data / "seteuk.db")) as connection:
        connection.row_factory = sqlite3.Row
        tables = {name: [dict(row) for row in connection.execute("SELECT * FROM %s ORDER BY id" % name)]
                  for name in TABLES}
        settings = dict(connection.execute("SELECT key,value FROM settings"))
    return {"rows": tables, "settings": {key: settings.get(key) for key in PRESERVED},
            "audio_sha256": digest(data / "audio" / "2099" / "01" / "synthetic-upgrade.wav"),
            "existing_backup_sha256": digest(data.parent / "synthetic-cloud-folder" / "keep-existing.txt")}


def prepare(installed, data):
    assert not data.exists(), "Upgrade fixture must start in a new directory"
    os.environ["SETEUK_DATA"] = str(data)
    sys.path.insert(0, str(installed / "app"))
    import db
    import version
    db.init()
    audio = data / "audio" / "2099" / "01" / "synthetic-upgrade.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 1600)
    destination = data.parent / "synthetic-cloud-folder"
    destination.mkdir(exist_ok=True)
    (destination / "keep-existing.txt").write_text("Synthetic existing backup — preserve me", encoding="utf-8")
    db.set_settings({"backup_folder": str(destination), "backup_audio": "1",
                     "backup_folder_last": "2099-01-01 09:00", "backup_audio_last": "2099-01-01 09:00",
                     "teacher_name": "합성 업그레이드 시험", "onboarded": "1", "profile_asked": "1",
                     "sheets_auto": "0", "drive_backup": "0", "auto_update": "0", "update_check": "0",
                     "telemetry": "0", "text_sync": "0", "downloads_import": "0", "drive_inbox": "0",
                     "voicememo_enabled": "0", "notes_enabled": "0", "auto_process": "0",
                     "inbox_dir": str(data.parent / "synthetic-inbox")})
    connection = db.connect()
    try:
        connection.execute("INSERT INTO classes(id,year,semester,grade,class_no,subject,label,kind) "
                           "VALUES (1,2099,1,1,1,'합성 과학','합성 시험반','교과')")
        connection.execute("INSERT INTO students(id,class_id,number,name,memo) VALUES (1,1,1,'합성학생','보존할 메모')")
        connection.execute("INSERT INTO recordings(id,class_id,title,recorded_at,audio_path,transcript,status) "
                           "VALUES (1,1,'합성 녹음','2099-01-01 09:00',?,'합성학생이 관찰 결과를 설명함.','확인필요')",
                           (str(audio),))
        connection.execute("INSERT INTO notes(id,student_id,recording_id,date,content,area) "
                           "VALUES (1,1,1,'2099-01-01','합성 관찰기록: 결과를 설명함.','subject')")
        connection.execute("INSERT INTO drafts(id,student_id,content,status,area) "
                           "VALUES (1,1,'합성 확정 초안: 실험 결과를 설명함.','확정','subject')")
        connection.commit()
    finally:
        connection.close()
    print(json.dumps({"prepared_with_version": version.VERSION, "data_dir": str(data)}, ensure_ascii=False))


def running(data, expected):
    status = api("/api/version")
    assert status["version"] == expected, status
    settings = api("/api/settings")
    assert Path(settings["data_dir"]).resolve() == data, "Running app uses the wrong data directory"
    return settings


def verify(data, baseline):
    before = json.loads(baseline.read_text(encoding="utf-8"))
    assert before["data_dir"] == str(data), "Baseline data path differs"
    after = snapshot(data)
    for table, rows in before["snapshot"]["rows"].items():
        actual = after["rows"][table]
        assert len(actual) == len(rows), "Row count changed: " + table
        for old, new in zip(rows, actual):
            assert all(new.get(key) == value for key, value in old.items()), "Stored record changed: " + table
    for key in ("settings", "audio_sha256", "existing_backup_sha256"):
        assert after[key] == before["snapshot"][key], "Upgrade changed " + key
    backup = api("/api/backup-folder")
    assert Path(backup["folder"]).resolve() == data.parent / "synthetic-cloud-folder", backup
    assert backup["audio_enabled"], "Audio backup consent was lost"
    result = api("/api/backup-folder/now", {})
    assert not result.get("error") and not result.get("audio_error"), result
    summary = result["audio_summary"]
    copied = Path(summary["folder"]) / "audio" / "2099" / "01" / "synthetic-upgrade.wav"
    assert digest(copied) == after["audio_sha256"], "Configured audio backup no longer works"
    assert digest(data.parent / "synthetic-cloud-folder" / "keep-existing.txt") == after["existing_backup_sha256"]
    return {"from_version": before["version"], "to_version": api("/api/version")["version"],
            "same_data_directory": True, "preserved_rows": {key: len(value) for key, value in after["rows"].items()},
            "preserved_settings": after["settings"], "audio_sha256": after["audio_sha256"],
            "existing_backup_preserved": True, "configured_audio_backup_verified": True,
            "remote_cloud_sync_tested": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "capture", "verify"))
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    assert sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true", "Actions Windows only"
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    data = Path(os.environ["SETEUK_DATA"]).resolve()
    assert data == workspace / "upgrade-testdata", "Only disposable upgrade fixtures are allowed"
    baseline = workspace / "upgrade-baseline.json"
    if args.mode == "prepare":
        prepare(args.installed.resolve(), data)
        return
    settings = running(data, args.version)
    if args.mode == "capture":
        value = snapshot(data)
        assert all(settings.get(key) == val for key, val in value["settings"].items())
        baseline.write_text(json.dumps({"version": args.version, "data_dir": str(data), "snapshot": value},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        print("Baseline captured from running installed app", args.version)
    else:
        report = verify(data, baseline)
        (workspace / "windows-upgrade-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
