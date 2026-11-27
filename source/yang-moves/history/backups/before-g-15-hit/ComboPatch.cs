using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;

if (args.Length != 3)
    throw new ArgumentException("Usage: ComboPatch <vanilla MainChar_ComboTree.uasset> <staging root> <inspection root>");

var moves = new (string Name, string Package)[]
{
    ("YangPushKick", "/Game/DB/AI/Archetypes/Yang/Attacks/P2Attacks/Yang_SidePushKick_FL"),
    ("YangRushSweep", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_Rush_Sweep_FL"),
    ("YangTripleHit", "/Game/DB/AI/Archetypes/Yang/Attacks/P1Attacks/Yang_TripleHit_FL"),
    ("YangMultiHit", "/Game/YangMoves/YangUnblockableMultiHit")
};

BuildUnblockableMultiHit(args[2], args[1]);

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



static void BuildUnblockableMultiHit(string inspectionRoot, string stage)
{
    const string attackName = "YangUnblockableMultiHit";
    const string tableName = "YangMultiHitHitbox";
    var content = Path.Combine(inspectionRoot, "Sifu", "Content");
    var source = Path.Combine(content, "DB", "AI", "Archetypes", "Yang", "Attacks");
    var attack = new UAsset(Path.Combine(source, "P1Attacks", "Yang_MultiHit.uasset"), EngineVersion.VER_UE4_26);
    var table = new UAsset(Path.Combine(source, "Yang_HitboxData.uasset"), EngineVersion.VER_UE4_26);
    if (!attack.VerifyBinaryEquality() || !table.VerifyBinaryEquality())
        throw new InvalidDataException("MultiHit sources do not round-trip.");

    var definition = attack.Exports.OfType<NormalExport>().Single(export => export.ObjectName.ToString() == "Yang_MultiHit");
    var attackData = definition.Data.OfType<StructPropertyData>().Single(property => property.Name.ToString() == "m_Attack");
    var hitboxes = (ArrayPropertyData)attackData["m_HitBoxes"];
    var usedRows = hitboxes.Value.Cast<StructPropertyData>().Select(hit =>
        ((NamePropertyData)((StructPropertyData)hit["m_HitRow"])["RowName"]).Value.ToString()).ToHashSet();
    if (hitboxes.Value.Length != 10 || usedRows.Count != 8)
        throw new InvalidDataException("Unexpected MultiHit hit windows.");

    var tableExport = table.Exports.OfType<DataTableExport>().Single();
    tableExport.Table.Data.RemoveAll(row => !usedRows.Contains(row.Name.ToString()));
    if (tableExport.Table.Data.Count != usedRows.Count)
        throw new InvalidDataException("Missing MultiHit hit data.");

    // EHitBoxDefenseMatrix values were read from this build's enum metadata.
    // Dodge=1, Deflect=2, Guard=4. Retain Dodge while removing Guard/Deflect.
    const int blockedDefenses = 2 | 4;
    foreach (var row in tableExport.Table.Data)
    {
        ((IntPropertyData)row["m_iHitboxDefenseMatrix"]).Value &= ~blockedDefenses;
        ((BoolPropertyData)row["m_bParriable"]).Value = false;
    }

    tableExport.ObjectName = FName.FromString(table, tableName);
    definition.ObjectName = FName.FromString(attack, attackName);
    var tableImport = attack.Imports.Single(import =>
        import.ClassName.ToString() == "DataTable" && import.ObjectName.ToString() == "Yang_HitboxData");
    tableImport.ObjectName = FName.FromString(attack, tableName);
    tableImport.OuterIndex.ToImport(attack).ObjectName = FName.FromString(attack, "/Game/YangMoves/" + tableName);

    var output = Path.Combine(stage, "YangMoves");
    Directory.CreateDirectory(output);
    attack.Write(Path.Combine(output, attackName + ".uasset"));
    var tablePath = Path.Combine(output, tableName + ".uasset");
    table.Write(tablePath);
    var readback = new UAsset(tablePath, EngineVersion.VER_UE4_26).Exports.OfType<DataTableExport>().Single();
    if (readback.Table.Data.Count != 8 || readback.Table.Data.Any(row =>
        (((IntPropertyData)row["m_iHitboxDefenseMatrix"]).Value & blockedDefenses) != 0 ||
        ((BoolPropertyData)row["m_bParriable"]).Value))
        throw new InvalidDataException("Guard/deflect verification failed.");
    Console.WriteLine("Verified 8 private MultiHit rows with Guard/Deflect disabled.");
}