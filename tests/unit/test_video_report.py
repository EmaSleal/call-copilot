"""Unit tests for src/video/report.py — HTML report generation."""

import zipfile

from src.db.database import Category, Segment, VideoSession


def _session(**overrides) -> VideoSession:
    defaults = dict(
        id=1, url="https://youtube.com/watch?v=abc", title="Test session",
        status="done", created_at="2026-01-01T00:00:00", html_report=None,
    )
    defaults.update(overrides)
    return VideoSession(**defaults)


class TestVideoPlayerInReport:
    def test_includes_video_tag_when_video_file_exists(self, tmp_path):
        from src.video.report import generate_html_report

        (tmp_path / "video.mp4").write_bytes(b"fake")

        report_path = generate_html_report(_session(), [], [], tmp_path)
        html = report_path.read_text(encoding="utf-8")

        assert '<video' in html
        assert 'src="video.mp4"' in html

    def test_omits_video_tag_when_no_video_file(self, tmp_path):
        from src.video.report import generate_html_report

        report_path = generate_html_report(_session(), [], [], tmp_path)
        html = report_path.read_text(encoding="utf-8")

        assert '<video' not in html

    def test_report_still_includes_segments_with_video_present(self, tmp_path):
        from src.video.report import generate_html_report

        (tmp_path / "video.mp4").write_bytes(b"fake")
        cat = Category(id=1, name="Técnico", description="", color="#4f46e5")
        seg = Segment(
            id=1, session_id=1, start_s=0.0, end_s=5.0,
            text="hola mundo", category_id=1,
        )

        report_path = generate_html_report(_session(), [seg], [cat], tmp_path)
        html = report_path.read_text(encoding="utf-8")

        assert "hola mundo" in html
        assert '<video' in html


class TestExportReportZip:
    def test_bundles_report_keyframes_and_video(self, tmp_path):
        from src.video.report import export_report_zip

        (tmp_path / "report.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / "frame_0000.jpg").write_bytes(b"fake-jpg")
        (tmp_path / "video.mp4").write_bytes(b"fake-mp4")
        (tmp_path / "audio.mp3").write_bytes(b"fake-mp3")  # transcription artifact

        zip_path = export_report_zip(tmp_path)
        names = set(zipfile.ZipFile(zip_path).namelist())

        assert names == {"report.html", "frame_0000.jpg", "video.mp4"}

    def test_omits_video_entry_when_no_video_file(self, tmp_path):
        from src.video.report import export_report_zip

        (tmp_path / "report.html").write_text("<html></html>", encoding="utf-8")
        (tmp_path / "frame_0000.jpg").write_bytes(b"fake-jpg")

        zip_path = export_report_zip(tmp_path)
        names = set(zipfile.ZipFile(zip_path).namelist())

        assert names == {"report.html", "frame_0000.jpg"}

    def test_raises_when_report_html_missing(self, tmp_path):
        import pytest

        from src.video.report import export_report_zip

        with pytest.raises(FileNotFoundError):
            export_report_zip(tmp_path)
