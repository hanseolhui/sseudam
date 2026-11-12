#!/bin/zsh
# 아이폰 앱을 App Store Connect 로 올리기:  ASC_KEY_ID=… ASC_ISSUER_ID=… tools/ios-testflight.sh [빌드번호]
# 아카이브(자동 서명) → App Store 용으로 내보내기 → 업로드. 빌드번호를 안 주면 1 올린다.
# 키 파일은 ~/.appstoreconnect/private_keys/AuthKey_<키 ID>.p8 (저장소에 넣지 않는다)
# 키를 주지 않으면 Xcode 에 로그인된 계정으로 서명해 ipa 만 만들고, 올리지는 않는다.
set -e
cd "$(dirname "$0")/.."
KEY=~/.appstoreconnect/private_keys/AuthKey_${ASC_KEY_ID:-none}.p8
YML=mobile/ios/project.yml; PBX=mobile/ios/Sseudam.xcodeproj/project.pbxproj
CUR=$(grep -E 'CURRENT_PROJECT_VERSION' $YML | grep -oE '[0-9]+')
N=${1:-$((CUR + 1))}
sed -i '' "s/CURRENT_PROJECT_VERSION: \"$CUR\"/CURRENT_PROJECT_VERSION: \"$N\"/" $YML
sed -i '' "s/CURRENT_PROJECT_VERSION = $CUR;/CURRENT_PROJECT_VERSION = $N;/g" $PBX
OUT=build/ios; rm -rf $OUT/Sseudam.xcarchive $OUT/export; mkdir -p $OUT
cat > $OUT/ExportOptions.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>method</key><string>app-store-connect</string>
<key>destination</key><string>export</string>
<key>teamID</key><string>967DUR6926</string>
<key>signingStyle</key><string>automatic</string>
<key>uploadSymbols</key><true/>
</dict></plist>
PLIST
if [ -n "${ASC_KEY_ID:-}" ] && [ -n "${ASC_ISSUER_ID:-}" ] && [ -f $KEY ]; then
  AUTH=(-allowProvisioningUpdates -authenticationKeyPath $KEY -authenticationKeyID $ASC_KEY_ID -authenticationKeyIssuerID $ASC_ISSUER_ID)
else
  AUTH=(-allowProvisioningUpdates); UPLOAD=0
fi
xcodebuild archive -project mobile/ios/Sseudam.xcodeproj -scheme Sseudam -configuration Release -destination 'generic/platform=iOS' \
  -archivePath $OUT/Sseudam.xcarchive -derivedDataPath $OUT/dd "${AUTH[@]}" | grep -E "error:|warning: unable|ARCHIVE" || true
[ -d $OUT/Sseudam.xcarchive ] || { echo "아카이브 실패"; exit 1; }
xcodebuild -exportArchive -archivePath $OUT/Sseudam.xcarchive -exportOptionsPlist $OUT/ExportOptions.plist -exportPath $OUT/export "${AUTH[@]}" | grep -E "error|EXPORT" || true
IPA=$(ls $OUT/export/*.ipa | head -1)
[ -f "$IPA" ] || { echo "내보내기 실패"; exit 1; }
if [ "${UPLOAD:-1}" = "1" ]; then
  xcrun altool --upload-app -f "$IPA" -t ios --apiKey $ASC_KEY_ID --apiIssuer $ASC_ISSUER_ID
  echo "빌드 $N 올림"
else
  echo "빌드 $N 만듦 (올리지 않음): $IPA"
fi
