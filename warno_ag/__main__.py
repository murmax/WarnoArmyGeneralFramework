import argparse
import json
import sys
from pathlib import Path
from .archives import scan
from .audit import audit_corpus
from .cndf import inspect_pack
from .modules import write_build
from .native import inspect_native
from .xrefs import build_xrefs, references_to
from .campaign import write_campaign
from .trial import write_trial
from .deployment import (activate_trial, deactivate_trial, install_trial, plan_trial,
                         rollback_trial, status_trial)
from .runtime import startup_smoke
from .modgen import prepare_modgen_project
from .full_campaign import (install_complete_full, reinstall_full, status_full,
                            uninstall_full)
from .authoring import compile_campaign
from .stress import write_stress_campaign
from .bruderkrieg import assemble_authored_candidate, package_authored_campaign


def main():
    parser = argparse.ArgumentParser(description="Offline WARNO Army General research")
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index")
    index.add_argument("game_root")
    index.add_argument("output")
    dec = sub.add_parser("recover")
    dec.add_argument("index")
    dec.add_argument("output")
    dec.add_argument("--variant", choices=["F0", "F1"], default="F0")
    dec.add_argument("--campaign")
    audit = sub.add_parser("audit")
    audit.add_argument("game_root")
    audit.add_argument("artifacts")
    native = sub.add_parser("inspect-native")
    native.add_argument("pack")
    native.add_argument("output")
    build = sub.add_parser('build', help='Build isolated offline research package; never installs it')
    build.add_argument('module')
    machine = sub.add_parser('native-code',help='Read-only executable analysis; never runs WARNO')
    machine.add_argument('exe')
    machine.add_argument('profile')
    refs = sub.add_parser('native-xrefs',help='Cache static direct/RIP references; optional target RVA')
    refs.add_argument('exe')
    refs.add_argument('--to',type=lambda s:int(s,0))
    mvp = sub.add_parser('mvp-build',help='Build isolated MVP campaign test data; never installs or launches')
    mvp.add_argument('manifest')
    mvp.add_argument('--require-complete',action='store_true',help='Fail unless full runtime acceptance exists')
    trial = sub.add_parser('trial-build', help='Prepare registration-only trial; no installation or game launch')
    trial.add_argument('profile')
    for command in ('trial-plan', 'trial-install'):
        trial = sub.add_parser(command, help='Inspect deployment' if command == 'trial-plan' else
                               'Explicitly install a NEW trial directory; never activates or launches')
        trial.add_argument('bundle')
        trial.add_argument('--game-root', required=True)
        trial.add_argument('--mod-parent', help='Dedicated mod directory; defaults to Saved Games')
    trial = sub.add_parser('trial-rollback', help='Move owned trial out of mod directory; retain every file')
    trial.add_argument('--mod-parent', help='Dedicated mod directory; defaults to Saved Games')
    trial = sub.add_parser('trial-status', help='Verify installed trial ownership, inventory and hashes')
    trial.add_argument('--mod-parent', help='Dedicated mod directory; defaults to Saved Games')
    for command in ('trial-activate', 'trial-deactivate'):
        trial = sub.add_parser(command, help='Exclusively activate trial with exact config backup' if command == 'trial-activate'
                               else 'Restore exact shared config saved by trial-activate')
        trial.add_argument('--mod-parent', help='Dedicated mod directory; defaults to Saved Games')
    runtime = sub.add_parser('runtime-startup', help='Launch an exclusively managed trial and record startup evidence')
    runtime.add_argument('--game-root', required=True)
    runtime.add_argument('--output', required=True)
    runtime.add_argument('--stable-seconds', type=float, default=20)
    modgen = sub.add_parser('prepare-modgen', help='Generate custom battalion sources in one ModGen project')
    modgen.add_argument('template')
    modgen.add_argument('project')
    modgen.add_argument('--campaign')
    modgen.add_argument('--profile')
    authored = sub.add_parser('campaign-compile', help='Compile public campaign YAML against a map profile')
    authored.add_argument('source')
    authored.add_argument('profile')
    authored.add_argument('destination')
    authored = sub.add_parser('campaign-build', help='Build a complete authored Bruderkrieg-map candidate')
    authored.add_argument('source')
    authored.add_argument('profile')
    authored.add_argument('base_candidate')
    authored.add_argument('destination')
    authored = sub.add_parser('campaign-package', help='Package campaign YAML and ModGen output as a complete verified bundle')
    authored.add_argument('source')
    authored.add_argument('profile')
    authored.add_argument('modgen_output')
    authored.add_argument('destination')
    authored.add_argument('--world-source')
    authored.add_argument('--event-images')
    authored.add_argument('--map-runtime', help='Verified new-map payload from an official world bake')
    editor_package = sub.add_parser('editor-public-package', help='Build a public campaign through a fresh official compiler workspace; never installs')
    editor_package.add_argument('source')
    editor_package.add_argument('profile')
    editor_package.add_argument('game_root')
    editor_package.add_argument('destination')
    editor_package.add_argument('--world-source')
    editor_package.add_argument('--event-images')
    editor_package.add_argument('--workspace-parent', help='Existing directory for the official ModGen workspace, e.g. on E:')
    stress = sub.add_parser('campaign-stress', help='Generate a standalone fully-authored scale campaign')
    stress.add_argument('destination')
    stress.add_argument('--count', type=int, default=128)
    world = sub.add_parser('world-compile', help='Compile explicit world YAML inputs; never bakes, installs or launches')
    world.add_argument('source')
    world.add_argument('destination')
    world.add_argument('--stock-scenery-archive')
    world.add_argument('--decor-set', default='Steelman')
    geotiff_info = sub.add_parser('geotiff-inspect', help='Read GeoTIFF CRS and render a north-up crop-picker preview')
    geotiff_info.add_argument('source')
    geotiff_info.add_argument('destination')
    geotiff_crop = sub.add_parser('geotiff-crop', help='Crop WGS84 GeoTIFF terrain into an editor south-up heightmap')
    geotiff_crop.add_argument('source')
    geotiff_crop.add_argument('west', type=float)
    geotiff_crop.add_argument('south', type=float)
    geotiff_crop.add_argument('east', type=float)
    geotiff_crop.add_argument('north', type=float)
    geotiff_crop.add_argument('resolution', type=int)
    geotiff_crop.add_argument('destination')
    geotiff_crop.add_argument('--elevation-ceiling-m', type=float, default=1600)
    geodata = sub.add_parser('geodata-import', help='Download Copernicus DEM and licensed OSM extract on demand, then render a new map')
    for coordinate in ('west', 'south', 'east', 'north'):
        geodata.add_argument(coordinate, type=float)
    geodata.add_argument('destination')
    geodata.add_argument('--cache', required=True)
    geodata.add_argument('--resolution', type=int, default=2048)
    geodata.add_argument('--surface-size', type=int, default=4096)
    geodata.add_argument('--elevation-ceiling-m', type=float, default=1600)
    geodata.add_argument('--zoom', type=int, default=12)
    pack_options = sub.add_parser('editor-pack-options', help='Inspect verified game transport choices for a tactical unit')
    pack_options.add_argument('unit')
    pack_options.add_argument('--transport')
    images = sub.add_parser('event-images-compile', help='Stage private event artwork and texture-bank source; never installs')
    images.add_argument('source')
    images.add_argument('destination')
    world_source = sub.add_parser('world-prepare', help='Prepare a fresh world LevelBuild source bundle; never installs')
    world_source.add_argument('source')
    world_source.add_argument('destination')
    world_source.add_argument('--scene-template-archive', required=True)
    world_source.add_argument('--stock-scenery-archive')
    world_source.add_argument('--decor-set', default='Steelman')
    catalog = sub.add_parser('editor-catalog', help='Export verified base-game and optional local-mod unit catalog')
    catalog.add_argument('base_root')
    catalog.add_argument('output')
    catalog.add_argument('--mod-root', action='append', default=[])
    editor_source = sub.add_parser('editor-source', help='Read campaign YAML and assets as lossless editor JSON; no build or install')
    editor_source.add_argument('source')
    editor_source.add_argument('profile', nargs='?')
    editor_image = sub.add_parser('editor-image', help='Normalize imported surface/event artwork to PNG')
    editor_image.add_argument('source')
    editor_image.add_argument('destination')
    editor_image.add_argument('--role', choices=('surface', 'event'), default='surface')
    game_catalog = sub.add_parser('editor-game-catalog', help='List installed source scenarios for editor import; excludes saves')
    game_catalog.add_argument('game_root')
    game_import = sub.add_parser('editor-game-import', help='Capture one installed source scenario and map for editing; never installs')
    game_import.add_argument('game_root')
    game_import.add_argument('scenario')
    game_import.add_argument('destination')
    game_import.add_argument('--visuals', action='store_true', help='Extract original pawn models and textures into a portable editor cache')
    game_import.add_argument('--progress', action='store_true', help='Stream editor import stages to stderr')
    game_import.add_argument('--visual-units-json', help='Also convert verified models requested by a public YAML project')
    game_visuals = sub.add_parser('editor-game-visuals', help='Extract native pawn models/textures for a captured scenario; no install')
    game_visuals.add_argument('source')
    game_visuals.add_argument('destination')
    single_visual = sub.add_parser('editor-strategic-visual', help='Extract one verified strategic pawn preview from a source snapshot or installed game; no install')
    single_visual.add_argument('source')
    single_visual.add_argument('unit_id')
    single_visual.add_argument('country')
    single_visual.add_argument('destination')
    native_template = sub.add_parser('native-template-augment',
                                     help='Combine prior official ModGen compatibility proofs; does not launch the game')
    native_template.add_argument('base_template')
    native_template.add_argument('official_config')
    native_template.add_argument('destination')
    native_script = sub.add_parser('editor-native-script-catalog',
                                   help='Read classified nodes of a captured native scenario graph')
    native_script.add_argument('source')
    native_script.add_argument('script', nargs='?')
    native_script.add_argument('projection', nargs='?')
    event_preview = sub.add_parser('editor-game-event-preview',
                                   help='Extract a stock strategic event portrait for editor preview')
    event_preview.add_argument('game_root')
    event_preview.add_argument('token')
    event_preview.add_argument('destination')
    native_event_preview = sub.add_parser('editor-native-event-preview',
        help='Extract an original scenario cutscene texture for editor preview')
    native_event_preview.add_argument('game_root')
    native_event_preview.add_argument('scenario')
    native_event_preview.add_argument('token')
    native_event_preview.add_argument('destination')
    unit_icons = sub.add_parser('editor-unit-icons', help='Extract localized original unit names and icon images for the editor')
    unit_icons.add_argument('game_root')
    unit_icons.add_argument('template_root')
    unit_icons.add_argument('destination')
    unit_icons.add_argument('--progress', action='store_true')
    game_visuals.add_argument('--visual-units-json')
    game_reference = sub.add_parser('editor-game-reference', help='Crop a captured game map for read-only YAML preview')
    game_reference.add_argument('source')
    game_reference.add_argument('visuals')
    game_reference.add_argument('destination')
    game_reference.add_argument('bounds', nargs=4, type=float)
    native_build = sub.add_parser('native-campaign-build', help='Build and verify edited native scenario artifacts; no packaging or install')
    native_build.add_argument('source')
    native_build.add_argument('profile')
    native_build.add_argument('destination')
    native_package = sub.add_parser('native-campaign-package', help='Package native campaign edits as a complete verified bundle; never installs')
    native_package.add_argument('source')
    native_package.add_argument('profile')
    native_package.add_argument('compiler_template')
    native_package.add_argument('destination')
    native_package.add_argument('--world-output')
    native_world = sub.add_parser('native-world-build', help='Rebuild edited native world under a private map identity using official tools')
    native_world.add_argument('source')
    native_world.add_argument('profile')
    native_world.add_argument('destination')
    for command in ('full-install', 'full-reinstall'):
        full = sub.add_parser(command, help='Install one complete verified Army General bundle')
        full.add_argument('bundle')
        full.add_argument('config')
        full.add_argument('--mod-parent')
    full = sub.add_parser('full-uninstall', help='Fully remove the owned Army General mod tree')
    full.add_argument('config')
    full.add_argument('--mod-parent')
    full = sub.add_parser('full-status', help='Verify the complete Army General installation')
    full.add_argument('config')
    full.add_argument('--mod-parent')
    workshop = sub.add_parser('workshop-export', help='Prepare a verified unpublished Workshop campaign tree')
    workshop.add_argument('bundle')
    workshop.add_argument('config')
    workshop.add_argument('destination')
    workshop.add_argument('--preview')
    workshop.add_argument('--publication-receipt')
    workshop = sub.add_parser('workshop-verify', help='Verify an unpublished Workshop export against its bundle')
    workshop.add_argument('stage')
    workshop.add_argument('bundle')
    workshop.add_argument('config')
    for command in ('workshop-plan-upload', 'workshop-prepare-upload'):
        workshop = sub.add_parser(command, help='Preflight or stage an official WARNO Workshop uploader workspace')
        workshop.add_argument('stage')
        workshop.add_argument('bundle')
        workshop.add_argument('config')
        workshop.add_argument('game_root')
        workshop.add_argument('--mod-parent')
    workshop = sub.add_parser('workshop-verify-subscriber',
                              help='Compare a Steam-downloaded Workshop item to a verified campaign stage')
    workshop.add_argument('stage')
    workshop.add_argument('bundle')
    workshop.add_argument('config')
    workshop.add_argument('item_directory')
    workshop = sub.add_parser('workshop-capture-upload',
                              help='Record the Steam item ID assigned by the official WARNO uploader')
    workshop.add_argument('stage')
    workshop.add_argument('bundle')
    workshop.add_argument('config')
    workshop.add_argument('--item-directory')
    args = parser.parse_args()
    if args.command == 'editor-game-reference':
        from .editor_reference import crop_game_reference
        print(json.dumps(crop_game_reference(args.source, args.visuals, args.bounds, args.destination), indent=2))
        return 0
    if args.command == 'editor-game-visuals':
        from .editor_visuals import capture_editor_visuals
        report = capture_editor_visuals(args.source, args.destination, public_visuals=args.visual_units_json)
        print(json.dumps({'models': len(report['models']), 'battalions': len(report['battalions']),
                          'issues': report['issues'], 'runtime_verified': False}, indent=2))
        return 0
    if args.command == 'editor-strategic-visual':
        from .editor_strategic_visual import capture_strategic_visual
        report = capture_strategic_visual(args.source, args.unit_id, args.country, args.destination)
        print(json.dumps({'unit_id': report['unit_id'], 'country': report['country'],
                          'models': len(report['models']), 'runtime_verified': False}, indent=2))
        return 0
    if args.command == 'native-template-augment':
        from .native_toolchain import augment_native_compiler_template

        print(json.dumps(augment_native_compiler_template(args.base_template,
            args.official_config, args.destination), indent=2))
        return 0
    if args.command == 'editor-native-script-catalog':
        from .editor_native_script import capture_native_script_catalog, capture_native_script_catalog_files

        if bool(args.script) != bool(args.projection):
            raise ValueError('Provide a source snapshot or manifest, script and projection files together')
        report = (capture_native_script_catalog_files(args.source, args.script, args.projection)
                  if args.script else capture_native_script_catalog(args.source))
        print(json.dumps(report, ensure_ascii=True))
        return 0
    if args.command == 'editor-game-event-preview':
        from .editor_event_preview import capture_game_event_preview

        print(json.dumps(capture_game_event_preview(args.game_root, args.token, args.destination), indent=2))
        return 0
    if args.command == 'editor-native-event-preview':
        from .editor_event_preview import capture_native_event_preview

        print(json.dumps(capture_native_event_preview(args.game_root, args.scenario,
                                                      args.token, args.destination), indent=2))
        return 0
    if args.command == 'native-world-build':
        from .native_editor import compile_native_source
        from .native_world import build_native_world
        report = build_native_world(compile_native_source(args.source, args.profile), args.destination)
        print(json.dumps({'map_name': report['map_name'], 'payload': report['payload'], 'verification': report['verification'],
                          'bake_verified': report['bake_verified'], 'runtime_verified': False}, indent=2))
        return 0
    if args.command == 'editor-image':
        from .editor_images import normalize_editor_image
        print(json.dumps(normalize_editor_image(args.source, args.destination, args.role), indent=2))
        return 0
    if args.command == 'native-campaign-package':
        from .native_package import package_native_campaign
        print(json.dumps(package_native_campaign(args.source, args.profile, args.compiler_template, args.destination, world_output=args.world_output), indent=2))
        return 0
    if args.command == 'native-campaign-build':
        from .native_editor_build import build_native_editor_artifacts
        report = build_native_editor_artifacts(args.source, args.profile, args.destination)
        print(json.dumps({'artifacts': str(Path(args.destination).resolve()), 'scenario': report['identity']['scenario'],
                          'changes': len(report['changes']), 'private_battalions': len(report['pawn_replacements']),
                          'installable': report['installable'], 'runtime_verified': False}, indent=2))
        return 0
    if args.command == 'editor-game-catalog':
        from .native_campaign_source import NativeCampaignReader
        print(json.dumps(NativeCampaignReader(args.game_root).catalog(), ensure_ascii=True, indent=2))
        return 0
    if args.command == 'editor-game-import':
        from .native_campaign_source import NativeCampaignReader, capture_native_campaign
        def progress(percent, stage):
            if args.progress:
                print(f'AGF_EDITOR_PROGRESS\t{percent}\t{stage}', file=sys.stderr, flush=True)
        progress(5, 'Reading source campaign and map')
        manifest = capture_native_campaign(NativeCampaignReader(args.game_root), args.scenario, args.destination)
        progress(18, 'Source campaign captured')
        if args.visuals:
            from .editor_visuals import capture_editor_visuals
            capture_editor_visuals(args.destination, Path(args.destination) / 'visuals',
                                   public_visuals=args.visual_units_json, progress=progress if args.progress else None)
        progress(92, 'Source visuals verified')
        print(json.dumps({'source': str(Path(args.destination).resolve()), 'scenario': manifest['scenario'],
                          'resources': len(manifest['resources']), 'runtime_verified': False}, indent=2))
        return 0
    if args.command == 'editor-unit-icons':
        from .editor_unit_icons import capture_unit_catalog
        def progress(percent, stage):
            if args.progress:
                print(f'AGF_EDITOR_PROGRESS\t{percent}\t{stage}', file=sys.stderr, flush=True)
        report = capture_unit_catalog(args.game_root, args.template_root, args.destination,
                                      progress=progress if args.progress else None)
        print(json.dumps({'catalog': str(Path(args.destination).resolve()),
                          'entries': report['catalog_entries'], 'icons': report['icon_files'],
                          'runtime_verified': False}, indent=2))
        return 0
    if args.command == 'editor-source':
        from .editor_source import read_editor_source
        print(json.dumps(read_editor_source(args.source, args.profile),
                         ensure_ascii=True, allow_nan=False, indent=2))
        return 0
    if args.command == 'geotiff-inspect':
        from .geotiff import inspect_geotiff
        print(json.dumps(inspect_geotiff(args.source, args.destination), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'geotiff-crop':
        from .geotiff import crop_geotiff
        print(json.dumps(crop_geotiff(args.source, [args.west, args.south, args.east, args.north],
                                     args.resolution, args.destination,
                                     elevation_ceiling_m=args.elevation_ceiling_m), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'geodata-import':
        from .geodata_import import import_geographic_map, cli_progress
        print(json.dumps(import_geographic_map(
            [args.west, args.south, args.east, args.north], args.destination, args.cache,
            resolution=args.resolution, surface_size=args.surface_size,
            elevation_ceiling_m=args.elevation_ceiling_m,
            zoom=args.zoom, progress=cli_progress), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'editor-pack-options':
        from .strategic_pack_options import strategic_pack_options
        print(json.dumps(strategic_pack_options(args.unit,args.transport),
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == 'world-prepare':
        from .stock_scenery import load_stock_scenery
        from .world_source import load_scene_template, prepare_world_source
        catalog = (load_stock_scenery(args.stock_scenery_archive, args.decor_set)
                   if args.stock_scenery_archive else None)
        report = prepare_world_source(args.source, args.destination,
                                      scene_template=load_scene_template(args.scene_template_archive),
                                      scenery_catalog=catalog)
        print(json.dumps(report, indent=2))
        return 0
    if args.command == 'editor-catalog':
        from .editor_catalog import write_editor_catalog
        print(json.dumps(write_editor_catalog(args.base_root, args.output, args.mod_root),
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == 'event-images-compile':
        from .event_images import compile_event_images
        print(json.dumps(compile_event_images(args.source, args.destination), indent=2))
        return 0
    if args.command == 'world-compile':
        from .stock_scenery import load_stock_scenery
        from .world_authoring import compile_world
        catalog = (load_stock_scenery(args.stock_scenery_archive, args.decor_set)
                   if args.stock_scenery_archive else None)
        _, report = compile_world(args.source, args.destination, scenery_catalog=catalog)
        print(json.dumps(report, indent=2))
        return 0
    if args.command == 'campaign-stress':
        source = write_stress_campaign(args.destination, args.count)
        print(json.dumps({'source': str(source), 'initial_battalions': args.count,
                          'reserve_battalions': 2, 'runtime_verified': False},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == 'campaign-package':
        report = package_authored_campaign(args.source, args.profile, args.modgen_output, args.destination,
                                           world_source=args.world_source, event_images=args.event_images,
                                           map_runtime=args.map_runtime)
        print(json.dumps({key: report[key] for key in ('candidate', 'config', 'bundle', 'runtime_verified')}, indent=2))
        return 0
    if args.command == 'editor-public-package':
        from .editor_public_package import package_public_editor_campaign

        report = package_public_editor_campaign(args.source, args.profile, args.game_root,
            args.destination, world_source=args.world_source, event_images=args.event_images,
            workspace_parent=args.workspace_parent)
        print(json.dumps({key: report['package'][key] for key in ('candidate', 'config', 'bundle', 'runtime_verified')}, indent=2))
        return 0
    if args.command == 'campaign-compile':
        _, report = compile_campaign(args.source, args.profile, args.destination)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'campaign-build':
        compiled, compile_report = compile_campaign(args.source, args.profile)
        report = assemble_authored_candidate(args.base_candidate, args.destination, compiled)
        print(json.dumps({"compile": compile_report, "build": report},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == 'prepare-modgen':
        print(json.dumps(prepare_modgen_project(args.template, args.project,
                                                args.campaign, args.profile),
                         ensure_ascii=False, indent=2))
        return 0
    if args.command in ('full-install', 'full-reinstall'):
        action = install_complete_full if args.command == 'full-install' else reinstall_full
        print(json.dumps(action(args.bundle, args.config, args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'full-uninstall':
        print(json.dumps(uninstall_full(args.config, args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'full-status':
        print(json.dumps(status_full(args.config, args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'workshop-export':
        from .workshop import export_workshop_stage
        report = export_workshop_stage(args.bundle, args.config, args.destination,
                                       preview=args.preview,
                                       publication_receipt=args.publication_receipt)
        print(json.dumps({'stage': args.destination,
                          'source_bundle_id': report['source_bundle_id'],
                          'publisher_folder': report['publisher_folder'],
                          'workshop_id': report['workshop_id'],
                          'file_count': len(report['files']),
                          'steam_upload_performed': False}, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'workshop-verify':
        from .workshop import verify_workshop_stage
        print(json.dumps(verify_workshop_stage(args.stage, args.bundle, args.config),
                         ensure_ascii=False, indent=2))
        return 0
    if args.command in ('workshop-plan-upload', 'workshop-prepare-upload'):
        from .workshop import plan_official_upload, prepare_official_upload
        action = plan_official_upload if args.command == 'workshop-plan-upload' else prepare_official_upload
        print(json.dumps(action(args.stage, args.bundle, args.config, args.game_root,
                                mod_parent=args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'workshop-verify-subscriber':
        from .workshop import verify_workshop_subscriber
        print(json.dumps(verify_workshop_subscriber(args.stage, args.bundle, args.config,
                                                    args.item_directory), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'workshop-capture-upload':
        from .workshop import capture_official_upload
        print(json.dumps(capture_official_upload(args.stage, args.bundle, args.config,
                                                 item_directory=args.item_directory), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'trial-build':
        print(write_trial(args.profile))
        return 0
    if args.command in ('trial-plan', 'trial-install'):
        action = plan_trial if args.command == 'trial-plan' else install_trial
        print(json.dumps(action(args.bundle, args.game_root, args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'trial-rollback':
        print(json.dumps(rollback_trial(args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'trial-status':
        print(json.dumps(status_trial(args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command in ('trial-activate', 'trial-deactivate'):
        action = activate_trial if args.command == 'trial-activate' else deactivate_trial
        print(json.dumps(action(args.mod_parent), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'runtime-startup':
        report = startup_smoke(args.game_root, args.output, args.stable_seconds)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['startup']['status'] == 'pass' else 1
    if args.command == 'mvp-build':
        target, report = write_campaign(args.manifest,args.require_complete)
        print(target)
        print(f"{len(report['cases'])} data cases; ready=false; installable=false; runtime_verified=false")
        return 0
    if args.command == 'native-xrefs':
        database=build_xrefs(args.exe)
        print(json.dumps(references_to(database,args.to),indent=2) if args.to is not None else database)
        return 0
    if args.command == 'native-code':
        result=inspect_native(args.exe,json.loads(Path(args.profile).read_text(encoding='utf-8')))
        print(f"Recorded {len(result['functions'])} native functions; verified {len(result['checks'])} static checks; hook_ready=false")
        return 0
    if args.command == 'build':
        print(write_build(json.loads(Path(args.module).read_text(encoding='utf-8'))))
        return 0
    if args.command == "index":
        result = scan(args.game_root, args.output)
        return int(bool(result["errors"] or result["conflicts"]))
    if args.command == "recover":
        from .recover import recover
        result = recover(args.index, args.output, args.variant, args.campaign)
        return int(bool(result["failures"]))
    if args.command == "audit":
        result = audit_corpus(args.game_root,args.artifacts)
        return int(bool(result["errors"]))
    if args.command == "inspect-native":
        print(inspect_pack(args.pack,args.output))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
