.PHONY: help inventory verify smoke fetch-roomflow pterodactyl-release server-image derivative-image android ios-simulator checksums

help:
	@echo "Floodman Operations developer commands"
	@echo "  make inventory          Regenerate route/environment/source inventories"
	@echo "  make verify             Run static source and package checks"
	@echo "  make smoke              Run packaged server smoke tests"
	@echo "  make fetch-roomflow     Fetch pinned RoomFlow source"
	@echo "  make pterodactyl-release Rebuild and verify current Pterodactyl upload files"
	@echo "  make derivative-image   Build a new image on the existing AIO base"
	@echo "  make server-image       Build the complete AIO image"
	@echo "  make android            Compile/test/lint/build Android"
	@echo "  make ios-simulator      Generate and build the iOS simulator project (macOS only)"

inventory:
	python3 scripts/generate_inventory.py

verify: inventory
	python3 scripts/verify_repo.py

smoke:
	bash scripts/run_server_smoke_tests.sh

fetch-roomflow:
	bash scripts/fetch-roomflow.sh

pterodactyl-release:
	python3 scripts/package_pterodactyl_release.py
	python3 scripts/verify_pterodactyl_release.py

derivative-image:
	docker build --pull --no-cache -f containers/derivative/Dockerfile -t floodman-operations:4.6.8 .

server-image:
	docker build --pull --no-cache -f containers/base-aio/Dockerfile -t floodman-business-suite-aio:4.6.8 .

android:
	cd apps/android && gradle --no-daemon :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:bundleRelease

ios-simulator:
	cd apps/ios && xcodegen generate && xcodebuild -project FloodmanOperations.xcodeproj -scheme FloodmanOperations -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO build

checksums:
	python3 scripts/generate_checksums.py
