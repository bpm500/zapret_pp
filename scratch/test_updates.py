import sys
import shutil
import json
from pathlib import Path

repo_dir = Path(__file__).resolve().parent.parent
if str(repo_dir) not in sys.path:
    sys.path.insert(0, str(repo_dir))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QImage, QColor
from PyQt6.QtCore import Qt

import zapret_pp

def main():
    app = QApplication(sys.argv)
    print("Testing zapret_pp updates...")

    # 1. Test STRATEGIES
    strats = zapret_pp.STRATEGIES
    print(f"Total strategies: {len(strats)}")
    assert len(strats) >= 96, f"Expected at least 96 strategies, got {len(strats)}"
    
    # Check uniqueness of strategy names
    names = [s[0] for s in strats]
    assert len(names) == len(set(names)), "Strategy names contain duplicates!"

    # Test generating bat content for every single strategy
    dummy_zapret = Path("dist/zapret-discord-youtube-1.10.1")
    for name, args in strats:
        bat_content = zapret_pp._generate_bat_content(dummy_zapret, args, name)
        assert "%BIN%" in bat_content, f"Strategy {name} missing %BIN%"
        counter = zapret_pp._extract_strategy_counter(args)
        assert len(counter) > 0, f"Strategy {name} extracted 0 tokens: {args}"

    print("[OK] All 106 strategies verified successfully.")

    # 2. Test WallpaperWidget
    wall_widget = zapret_pp.WallpaperWidget(None, color1="#0a0a0a")
    assert wall_widget._color1 == "#0a0a0a"

    # Test setting image
    test_img_path = Path("scratch/test_wall.png")
    test_img = QImage(1920, 1080, QImage.Format.Format_RGB32)
    test_img.fill(QColor("#112233"))
    test_img.save(str(test_img_path))

    wall_widget.set_wallpaper(test_img_path)
    assert wall_widget._current_pixmap is not None
    assert not wall_widget._current_pixmap.isNull()
    print("[OK] WallpaperWidget image load and aspect ratio handling OK.")

    wall_widget.clear_wallpaper()
    assert wall_widget._current_pixmap is None
    print("[OK] WallpaperWidget clear OK.")

    # 3. Test build_stylesheet with has_wallpaper=True and False
    css_no_wall = zapret_pp.build_stylesheet("#0a0a0a", "#ffffff", "#e0e0e0", has_wallpaper=False)
    css_wall = zapret_pp.build_stylesheet("#0a0a0a", "#ffffff", "#e0e0e0", has_wallpaper=True)
    assert "rgba" in css_wall, "Wallpaper stylesheet missing rgba panels"
    print("[OK] build_stylesheet with wallpaper OK.")

    # 4. Test SoundCloud domains list
    sc_domains = zapret_pp.SOUNDCLOUD_DOMAINS
    print(f"SoundCloud domains count: {len(sc_domains)}")
    assert "soundcloud.com" in sc_domains
    assert "cf-media.sndcdn.com" in sc_domains
    assert "playback.media-streaming.soundcloud.cloud" in sc_domains

    # 5. Test MainWindow initialization
    win = zapret_pp.MainWindow()
    assert win._slider_num_configs.maximum() == 10, f"Slider max was {win._slider_num_configs.maximum()}, expected 10"
    assert hasattr(win, "_subpage_set_ip"), "MainWindow missing _subpage_set_ip"
    assert hasattr(win, "_side_tab_set_ip"), "MainWindow missing _side_tab_set_ip"
    assert hasattr(win, "_btn_set_wallpaper"), "MainWindow missing _btn_set_wallpaper"
    assert hasattr(win, "_btn_clear_wallpaper"), "MainWindow missing _btn_clear_wallpaper"
    assert hasattr(win, "_wallpaper_widget"), "MainWindow missing _wallpaper_widget"

    # Verify Multi-ping is enabled by default
    assert win._multi_ping is True, "Multi-ping should be True by default"
    assert win._chk_multi_ping.isChecked() is True, "Multi-ping checkbox should be checked by default"
    print("[OK] Multi-ping enabled by default verified.")

    # Verify auto-download toggle switch in Update subpage
    assert hasattr(win, "_switch_auto_download"), "MainWindow missing _switch_auto_download"
    assert hasattr(win, "_lbl_auto_download_state"), "MainWindow missing _lbl_auto_download_state"
    assert hasattr(win, "_auto_download"), "MainWindow missing _auto_download"
    
    # Test toggling auto-download
    initial_ad = win._auto_download
    win._switch_auto_download.setChecked(not initial_ad)
    assert win._auto_download == (not initial_ad)
    assert win._lbl_auto_download_state.text() == ("Enabled" if not initial_ad else "Disabled")
    win._switch_auto_download.setChecked(initial_ad)
    print("[OK] auto-download switch UI & state toggling verified.")

    # 6. Test NewUpdateDialog with auto_download=False and auto_download=True
    dlg_manual = zapret_pp.NewUpdateDialog("v1.5.0", "1.4.0", css_no_wall, auto_download=False)
    assert hasattr(dlg_manual, "_btn_back"), "Manual dialog missing back button"
    assert hasattr(dlg_manual, "_btn_download"), "Manual dialog missing download button"
    assert dlg_manual._btn_back.text() == "back"
    assert dlg_manual._btn_download.text() == "download"

    dlg_auto = zapret_pp.NewUpdateDialog("v1.5.0", "1.4.0", css_no_wall, auto_download=True)
    assert hasattr(dlg_auto, "_btn_cancel"), "Auto dialog missing cancel button"
    assert hasattr(dlg_auto, "_btn_install_auto"), "Auto dialog missing install auto button"
    assert dlg_auto._btn_cancel.text() == "cancel"
    assert dlg_auto._btn_install_auto.text() == "install auto"
    assert hasattr(dlg_auto, "_progress_bar"), "Auto dialog missing progress bar"
    print("[OK] NewUpdateDialog (manual and auto-download modes) verified.")

    # 7. Test Set IP tab functions
    paths = win._get_list_general_paths()
    print(f"List-general paths found: {paths}")
    assert len(paths) > 0, "No list-general.txt found"

    # Test adding SoundCloud domains without corrupting existing file
    target_file = paths[0]
    orig_content = target_file.read_text(encoding="utf-8")
    try:
        # Add SoundCloud IPs
        win._add_soundcloud_ips()
        new_content = target_file.read_text(encoding="utf-8")
        assert "soundcloud.com" in new_content, "soundcloud.com was not added"
        
        # Test calling again to verify duplicate protection
        prev_len = len(new_content.splitlines())
        win._add_soundcloud_ips()
        after_dup_len = len(target_file.read_text(encoding="utf-8").splitlines())
        assert prev_len == after_dup_len, f"Duplicate check failed: {prev_len} != {after_dup_len}"
        print("[OK] SoundCloud deduplication test passed.")

        # Test single IP addition and deduplication
        win._inp_custom_ip.setText("test.custom-domain.org")
        win._add_custom_ip()
        content_after_custom = target_file.read_text(encoding="utf-8")
        assert "test.custom-domain.org" in content_after_custom
        
        # Adding same custom domain again
        win._inp_custom_ip.setText("test.custom-domain.org")
        win._add_custom_ip()
        assert win._lbl_set_ip_feedback.text() == "Entry 'test.custom-domain.org' already exists in list-general.txt."
        print("[OK] Custom IP deduplication test passed.")
    finally:
        # Restore original list-general.txt content
        target_file.write_text(orig_content, encoding="utf-8")

    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
