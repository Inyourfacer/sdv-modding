using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;

// Lists public members of types in the installed game / SMAPI DLLs, read with MetadataLoadContext (no game code runs).
//   apidump <gameDir> <TypeName> [<TypeName> ...]         human-readable (TypeName = full name, nested types with +)
//   apidump <gameDir> --gamedata                          JSON of every public type in StardewValley.GameData.dll:
//                                                         { "StardewValley.GameData.Objects.ObjectData": { "Name": "String", ... } }
var gameDir = args[0];
var paths = Directory.GetFiles(gameDir, "*.dll").Concat(Directory.GetFiles(RuntimeEnvironment.GetRuntimeDirectory(), "*.dll"));
using var mlc = new MetadataLoadContext(new PathAssemblyResolver(paths), "System.Private.CoreLib");
var asms = new[] { "Stardew Valley.dll", "StardewModdingAPI.dll", "StardewValley.GameData.dll", "MonoGame.Framework.dll" }
    .Where(f => File.Exists(Path.Combine(gameDir, f)))
    .Select(f => mlc.LoadFromAssemblyPath(Path.Combine(gameDir, f))).ToList();

static string TypeText(Type t)
{
    if (t.IsGenericType)
    {
        var n = t.Name.Contains('`') ? t.Name[..t.Name.IndexOf('`')] : t.Name;
        return n + "<" + string.Join(", ", t.GetGenericArguments().Select(TypeText)) + ">";
    }
    return t.IsArray ? TypeText(t.GetElementType()!) + "[]" : t.Name;
}

if (args.Length > 1 && args[1] == "--gamedata")
{
    var gd = asms.First(a => a.GetName().Name == "StardewValley.GameData");
    var result = new SortedDictionary<string, SortedDictionary<string, string>>();
    foreach (var t in gd.GetTypes().Where(x => x.IsPublic || x.IsNestedPublic))
    {
        if (t.IsEnum) continue;
        var members = new SortedDictionary<string, string>();
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance))
            members[f.Name] = TypeText(f.FieldType);
        foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            members[p.Name] = TypeText(p.PropertyType);
        if (members.Count > 0)
            result[t.FullName!] = members;
    }
    Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
    return;
}

const BindingFlags F = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
foreach (var name in args.Skip(1))
{
    var t = asms.Select(a => a.GetType(name)).FirstOrDefault(x => x != null);
    if (t == null) { Console.WriteLine($"## {name}: NOT FOUND"); continue; }
    Console.WriteLine($"## {t.FullName}  (base {t.BaseType?.Name})");
    foreach (var m in t.GetMembers(F).OrderBy(x => x.MemberType).ThenBy(x => x.Name))
    {
        string vis = m switch
        {
            MethodBase mb => mb.IsPublic ? "public" : mb.IsFamily ? "protected" : "private",
            FieldInfo fi => fi.IsPublic ? "public" : fi.IsFamily ? "protected" : "private",
            _ => "public"
        };
        if (vis == "private") continue;
        string text = m switch
        {
            MethodInfo mi => $"{(mi.IsStatic ? "static " : "")}{mi.ReturnType.Name} {mi.Name}({string.Join(", ", mi.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name))})",
            FieldInfo fi => $"{(fi.IsStatic ? "static " : "")}field {fi.FieldType.Name} {fi.Name}",
            PropertyInfo pi => $"prop {pi.PropertyType.Name} {pi.Name}",
            ConstructorInfo ci => $"ctor({string.Join(", ", ci.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name))})",
            _ => m.MemberType + " " + m.Name
        };
        Console.WriteLine($"  {vis} {text}");
    }
}
