#!/usr/bin/env python3
"""Scaffold a Stardew Valley 1.6 mod.

Types: cp | smapi | smapi+cp | portraiture | fashionsense | alttextures

  python new_mod.py --type cp --name "Mira NPC" --out ./mods
  python new_mod.py --type smapi --name "Better Kegs" --out ./src --gmcm --harmony
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sdvlib import cp_format, dump_json, load_config, slug

PREFIX = {"cp": "[CP] ", "portraiture": "[Portraiture] ", "fashionsense": "[FS] ", "alttextures": "[AT] "}
PACK_FOR = {
    "cp": "Pathoschild.ContentPatcher",
    "portraiture": "Platonymous.Portraiture",
    "fashionsense": "PeacefulEnd.FashionSense",
    "alttextures": "PeacefulEnd.AlternativeTextures",
}


def manifest(name, author, uid, desc, version, pack_for=None, entry_dll=None, deps=None):
    m = {"Name": name, "Author": author, "Version": version, "Description": desc, "UniqueID": uid}
    if entry_dll:
        m["EntryDll"] = entry_dll
        m["MinimumApiVersion"] = "4.0.0"
    m["UpdateKeys"] = []
    if pack_for:
        m["ContentPackFor"] = {"UniqueID": pack_for}
    if deps:
        m["Dependencies"] = deps
    return m


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")
    path.write_text(text, encoding="utf-8")


def make_cp(root: Path, name, author, uid, desc, version, fmt, deps=None):
    dump_json(manifest(name, author, uid, desc, version, PACK_FOR["cp"], deps=deps), root / "manifest.json")
    write(root / "content.json", f"""{{
  "Format": "{fmt}",
  "ConfigSchema": {{}},
  "DynamicTokens": [],
  "Changes": [
    // {{ "Action": "Include", "FromFile": "data/example.json" }}
  ]
}}
""")
    dump_json({}, root / "i18n" / "default.json")
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)


def make_smapi(root: Path, name, author, uid, desc, version, gmcm, harmony):
    asm = slug(name)
    deps = [{"UniqueID": "spacechase0.GenericModConfigMenu", "IsRequired": False}] if gmcm else None
    dump_json(manifest(name, author, uid, desc, version, entry_dll=f"{asm}.dll", deps=deps), root / "manifest.json")
    write(root / f"{asm}.csproj", f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <AssemblyName>{asm}</AssemblyName>
    <RootNamespace>{asm}</RootNamespace>
    <Version>{version}</Version>
    <TargetFramework>net6.0</TargetFramework>
    <Nullable>enable</Nullable>
    <LangVersion>latest</LangVersion>{chr(10) + '    <EnableHarmony>true</EnableHarmony>' if harmony else ''}
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Pathoschild.Stardew.ModBuildConfig" Version="4.4.0" />
  </ItemGroup>
</Project>
""")
    gmcm_call = "\n        helper.Events.GameLoop.GameLaunched += OnGameLaunched;" if gmcm else ""
    gmcm_body = """

    private void OnGameLaunched(object? sender, GameLaunchedEventArgs e)
    {
        var gmcm = Helper.ModRegistry.GetApi<IGenericModConfigMenuApi>("spacechase0.GenericModConfigMenu");
        if (gmcm is null) return;
        gmcm.Register(ModManifest, reset: () => Config = new ModConfig(), save: () => Helper.WriteConfig(Config));
        gmcm.AddBoolOption(ModManifest, name: () => Helper.Translation.Get("config.enabled"),
            getValue: () => Config.Enabled, setValue: v => Config.Enabled = v);
    }""" if gmcm else ""
    harmony_using = "using HarmonyLib;\n" if harmony else ""
    harmony_init = "\n        new Harmony(ModManifest.UniqueID).PatchAll();" if harmony else ""
    write(root / "ModEntry.cs", f"""{harmony_using}using StardewModdingAPI;
using StardewModdingAPI.Events;
using StardewValley;

namespace {asm};

internal sealed class ModEntry : Mod
{{
    internal static IMonitor Log = null!;
    private ModConfig Config = null!;

    public override void Entry(IModHelper helper)
    {{
        Log = Monitor;
        Config = helper.ReadConfig<ModConfig>();{gmcm_call}
        helper.Events.GameLoop.SaveLoaded += OnSaveLoaded;
        helper.Events.Content.AssetRequested += OnAssetRequested;{harmony_init}
    }}

    private void OnSaveLoaded(object? sender, SaveLoadedEventArgs e)
    {{
    }}

    private void OnAssetRequested(object? sender, AssetRequestedEventArgs e)
    {{
        // if (e.NameWithoutLocale.IsEquivalentTo($"Mods/{{ModManifest.UniqueID}}/Objects"))
        //     e.LoadFromModFile<Microsoft.Xna.Framework.Graphics.Texture2D>("assets/objects.png", AssetLoadPriority.Medium);
    }}{gmcm_body}
}}
""")
    write(root / "ModConfig.cs", f"""namespace {asm};

public sealed class ModConfig
{{
    public bool Enabled {{ get; set; }} = true;
}}
""")
    if gmcm:
        write(root / "IGenericModConfigMenuApi.cs", f"""using System;
using StardewModdingAPI;

namespace {asm};

/// <summary>Subset of GMCM's API. Add members copied from GMCM's IGenericModConfigMenuApi.cs as needed.</summary>
public interface IGenericModConfigMenuApi
{{
    void Register(IManifest mod, Action reset, Action save, bool titleScreenOnly = false);
    void AddBoolOption(IManifest mod, Func<bool> getValue, Action<bool> setValue, Func<string> name, Func<string>? tooltip = null, string? fieldId = null);
    void AddNumberOption(IManifest mod, Func<int> getValue, Action<int> setValue, Func<string> name, Func<string>? tooltip = null, int? min = null, int? max = null, int? interval = null, Func<int, string>? formatValue = null, string? fieldId = null);
    void AddKeybind(IManifest mod, Func<SButton> getValue, Action<SButton> setValue, Func<string> name, Func<string>? tooltip = null, string? fieldId = null);
}}
""")
    dump_json({"config.enabled": "Enabled"} if gmcm else {}, root / "i18n" / "default.json")
    (root / "assets").mkdir(parents=True, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["cp", "smapi", "smapi+cp", "portraiture", "fashionsense", "alttextures"])
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default=".")
    ap.add_argument("--author")
    ap.add_argument("--uid", help="UniqueID override")
    ap.add_argument("--description", default="")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--gmcm", action="store_true", help="SMAPI: add Generic Mod Config Menu integration")
    ap.add_argument("--harmony", action="store_true", help="SMAPI: enable Harmony")
    ap.add_argument("--config")
    a = ap.parse_args()

    cfg = load_config(a.config)
    author = a.author or cfg.get("author") or "Author"
    cfg_prefix = cfg.get("uniqueid_prefix")
    prefix = slug(a.author) if a.author else (cfg_prefix if cfg_prefix and cfg_prefix != "YourName" else slug(author))
    uid = a.uid or f"{prefix}.{slug(a.name)}"
    out = Path(a.out)
    fmt = cp_format(cfg)
    made = []

    if a.type in ("smapi", "smapi+cp"):
        root = out / a.name
        make_smapi(root, a.name, author, uid, a.description, a.version, a.gmcm, a.harmony)
        made.append(root)
    if a.type in ("cp", "smapi+cp"):
        cp_uid = uid if a.type == "cp" else uid + ".CP"
        deps = [{"UniqueID": uid}] if a.type == "smapi+cp" else None
        root = out / f"{PREFIX['cp']}{a.name}"
        make_cp(root, a.name if a.type == "cp" else a.name + " (Content)", author, cp_uid, a.description, a.version, fmt, deps)
        made.append(root)
    if a.type == "portraiture":
        root = out / f"{PREFIX['portraiture']}{a.name}"
        dump_json(manifest(a.name, author, uid, a.description, a.version, PACK_FOR["portraiture"]), root / "manifest.json")
        made.append(root)
    if a.type == "fashionsense":
        root = out / f"{PREFIX['fashionsense']}{a.name}"
        dump_json(manifest(a.name, author, uid, a.description, a.version, PACK_FOR["fashionsense"]), root / "manifest.json")
        for d in ("Hairs", "Accessories", "Hats", "Shirts", "Pants", "Sleeves", "Shoes"):
            (root / d).mkdir(parents=True, exist_ok=True)
        made.append(root)
    if a.type == "alttextures":
        root = out / f"{PREFIX['alttextures']}{a.name}"
        dump_json(manifest(a.name, author, uid, a.description, a.version, PACK_FOR["alttextures"]), root / "manifest.json")
        (root / "Textures").mkdir(parents=True, exist_ok=True)
        made.append(root)

    for m in made:
        print(f"created {m}")
    print(f"UniqueID: {uid}" + (f"  (CP Format {fmt})" if "cp" in a.type else ""))


if __name__ == "__main__":
    main()
