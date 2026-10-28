[app]
title = Telegram Date Studio
package.name = datestudio
package.domain = org.datestudio
source.dir = .
source.include_exts = py,png,ttf,otf,tgs,json,txt
source.include_patterns = assets/*,src/*,src/*/*
source.exclude_dirs = bin,.buildozer,__pycache__
version = 0.1.0
requirements = python3,kivy==2.3.0,pillow,numpy,fonttools,plyer,pyjnius,android
orientation = portrait
fullscreen = 0
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.ndk = 25b
android.ndk_api = 24
p4a.branch = v2024.01.21
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
