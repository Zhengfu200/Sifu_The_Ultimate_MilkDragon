using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;

if (args.Length != 2)
    throw new ArgumentException("Usage: ComboPatch <vanilla MainChar_ComboTree.uasset> <staging root>");

var moves = new (string Name, string Package)[]
{
    ("YangPushKick", "/Game/DB/AI/Archetypes/Yang/Attacks/P2Attacks/Yang_SidePushKick_FL"),
    ("YangRushSweep", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_Rush_Sweep_FL"),
    ("YangTripleHit", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_TripleHit_FL"),
    ("YangRushPunch", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_Rush_KhapChoy_FL"),
    ("YangDoubleElbow", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_DoubleElbowStrike_FL"),
    ("YangTriplePunish", "/Game/DB/AI/Archetypes/Yang/Attacks/P2Attacks/Yang_TripleHitPunish_FR")
};

foreach (var move in moves)
{
    var asset = new UAsset(args[0], EngineVersion.VER_UE4_26);
    if (!asset.VerifyBinaryEquality())
        throw new InvalidDataException("The input combo does not round-trip.");

    var combo = asset.Exports.OfType<NormalExport>().Single(export => export.ObjectName.ToString() == "MainChar_ComboTree");
    var attacks = combo.Data.OfType<MapPropertyData>().Single(item => item.Name.ToString() == "m_Attacks");
    var nodes = combo.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "m_Nodes");
    var starts = combo.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "m_ComboStartNodesContainer");
    var attackIndex = combo.Data.OfType<IntPropertyData>().First(item => item.Name.ToString() == "m_DefaultAttacks").Value;
    var node = (StructPropertyData)nodes.Value[attackIndex];
    var attackInfos = (StructPropertyData)node["m_AttackInfos"];
    var originalAttack = attackInfos.Value.OfType<NamePropertyData>().First();
    if (!originalAttack.Value.ToString().EndsWith(".MainChar_Jab_FR", StringComparison.Ordinal))
        throw new InvalidDataException("Unexpected default light attack in the input combo.");

    var path = move.Package + "." + move.Package.Split('/')[^1];
    var originalEntry = attacks.Value.Single(entry => entry.Key is NamePropertyData key && key.Value == originalAttack.Value);
    var originalImport = ((ObjectPropertyData)originalEntry.Value).Value.ToImport(asset);
    var outer = originalImport.OuterIndex.ToImport(asset);
    var packageIndex = asset.AddImport(new Import(outer.ClassPackage.ToString(), outer.ClassName.ToString(),
        new FPackageIndex(0), move.Package, false, asset));
    var attackImport = asset.AddImport(new Import(originalImport.ClassPackage.ToString(), originalImport.ClassName.ToString(),
        packageIndex, move.Package.Split('/')[^1], false, asset));

    var softKey = (NamePropertyData)originalEntry.Key.Clone();
    ReplacePath(softKey, asset, path);
    var hardValue = (ObjectPropertyData)originalEntry.Value.Clone();
    hardValue.Value = attackImport;
    attacks.Value.Add(softKey, hardValue);
    combo.SerializationBeforeSerializationDependencies.Add(attackImport);

    foreach (var slot in attackInfos.Value.OfType<NamePropertyData>())
        ReplacePath(slot, asset, path);
    var transitions = (StructPropertyData)node["m_Transitions"];
    ((ArrayPropertyData)transitions["m_Transitions"]).Value = [];

    // The default attack covers ordinary input. Drop contextual starts so that
    // a sprint, parry or proximity rule cannot select a different attack.
    starts.Value = [];
    combo.ObjectName = FName.FromString(asset, move.Name);

    var output = Path.Combine(args[1], "YangMoves", move.Name + ".uasset");
    Directory.CreateDirectory(Path.GetDirectoryName(output)!);
    asset.Write(output);

    var readback = new UAsset(output, EngineVersion.VER_UE4_26);
    var written = readback.Exports.OfType<NormalExport>().Single(export => export.ObjectName.ToString() == move.Name);
    var writtenNodes = written.Data.OfType<ArrayPropertyData>().Single(item => item.Name.ToString() == "m_Nodes");
    var writtenAttack = (StructPropertyData)((StructPropertyData)writtenNodes.Value[attackIndex])["m_AttackInfos"];
    var slots = writtenAttack.Value.OfType<NamePropertyData>().ToArray();
    if (slots.Length != 4 || slots.Any(slot => slot.Value.ToString() != path))
        throw new InvalidDataException("Attack reference verification failed.");
    Console.WriteLine($"{move.Name}: {path}");
}

static void ReplacePath(NamePropertyData slot, UAsset asset, string path)
{
    slot.Value = FName.FromString(asset, path);
}


