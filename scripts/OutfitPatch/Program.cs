using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;

const string originalMesh = "/Game/Characters/MainChar/M/Meshes/SK_M_MainChar_01.SK_M_MainChar_01";
const string nailoongMesh = "/Game/Characters/MainChar/M/Nailoong/SK_Nailoong.SK_Nailoong";
const string wandererMesh = "/Game/Characters/MainChar/M/Nailoong/SK_Nailoong_Wanderer.SK_Nailoong_Wanderer";
const string tongjiMesh = "/Game/Characters/MainChar/M/Nailoong/SK_Nailoong_Tongji.SK_Nailoong_Tongji";
const int urbanFlair = 15;
const string testMesh = "/Game/Characters/MainChar/M/TU04/YellowJumpsuit/Meshes/SK_M_MainChar_YellowSuit.SK_M_MainChar_YellowSuit";

var variant = args.Length == 5 && args[2] is ("wanderer" or "tongji");
if (!variant && (args.Length != 3 || args[2] is not ("test" or "nailoong" or "nailoong-test")))
{
    Console.Error.WriteLine("Usage: OutfitPatch <original .uasset> <output .uasset> <test|nailoong|nailoong-test|(wanderer|tongji) index original-mesh-path>");
    return 2;
}

var input = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args[1]);
if (string.Equals(input, output, StringComparison.OrdinalIgnoreCase))
    throw new ArgumentException("The patch must be written to a separate directory.");

var asset = new UAsset(input, EngineVersion.VER_UE4_26);
if (!asset.VerifyBinaryEquality())
    throw new InvalidDataException("The original blueprint does not round-trip through UAssetAPI.");

var outfits = OutfitEntries(asset, "/MainChar/M/");
var before = MeshPaths(outfits);
var femaleBefore = MeshPaths(OutfitEntries(asset, "/MainChar/W/"));
if (before[0] != originalMesh)
    throw new InvalidDataException($"Unexpected male default mesh {before[0]}.");

var target = args[2] == "test" ? testMesh : nailoongMesh;
var expected = before.ToArray();
if (variant)
{
    if (!int.TryParse(args[3], out var index) || index < 1 || index >= outfits.Length || before[index] != args[4])
        throw new ArgumentException("The requested slot does not match the original male outfit.");
    if (((MapPropertyData)outfits[index]["m_OverrideMaterial"]).Value.Count != 0 ||
        ((NamePropertyData)((StructPropertyData)outfits[index]["m_props"])["RowName"]).Value.ToString() != "None")
        throw new ArgumentException("The requested slot has material overrides or an accessory.");
    expected[0] = nailoongMesh;
    if (args[2] == "tongji")
    {
        const string streetwear = "/Game/Characters/MainChar/M/TU06/StreetwearOutfit/Meshes/SK_M_MainChar_StreetwearOutfit.SK_M_MainChar_StreetwearOutfit";
        if (index == urbanFlair || before.Length <= urbanFlair || before[urbanFlair] != streetwear)
            throw new InvalidDataException("The Tongji slot overlaps the existing Wanderer outfit or the Urban flair slot changed.");
        expected[urbanFlair] = wandererMesh;
        expected[index] = tongjiMesh;
    }
    else
        expected[index] = wandererMesh;
}
else
    Array.Fill(expected, target, 0, args[2] == "nailoong" ? 1 : outfits.Length);

for (var i = 0; i < outfits.Length; i++)
{
    if (expected[i] == before[i])
        continue;
    var mesh = (SoftObjectPropertyData)outfits[i]["m_Mesh"];
    var value = mesh.Value;
    value.AssetPath.AssetName = FName.FromString(asset, expected[i]);
    mesh.Value = value;
}

Directory.CreateDirectory(Path.GetDirectoryName(output)!);
asset.Write(output);
var written = new UAsset(output, EngineVersion.VER_UE4_26);
var after = MeshPaths(OutfitEntries(written, "/MainChar/M/"));
if (!after.SequenceEqual(expected) || !MeshPaths(OutfitEntries(written, "/MainChar/W/")).SequenceEqual(femaleBefore))
    throw new InvalidDataException("The patched blueprint contains unexpected outfit changes.");

var changes = Enumerable.Range(0, after.Length).Where(i => before[i] != after[i]).ToArray();
foreach (var index in changes)
    Console.WriteLine($"Male outfit {index}: {after[index]}");
Console.WriteLine($"Verified {after.Length - changes.Length} other male and {femaleBefore.Length} female outfit references.");
return 0;

static string[] MeshPaths(StructPropertyData[] outfits) =>
    outfits.Select(outfit => ((SoftObjectPropertyData)outfit["m_Mesh"]).Value.AssetPath.AssetName.ToString()).ToArray();

static StructPropertyData[] OutfitEntries(UAsset asset, string genderPath)
{
    var player = asset.Exports.OfType<NormalExport>()
        .Single(export => export.ObjectName.ToString() == "PlayerFighting_GEN_VARIABLE");
    var genders = player.Data.OfType<StructPropertyData>()
        .Where(property => property.Name.ToString() == "m_ByGenderData");
    var matching = genders.Single(gender => ((ArrayPropertyData)gender["m_Outfits"]).Value.Any(
        entry => ((SoftObjectPropertyData)((StructPropertyData)entry)["m_Mesh"]).Value.AssetPath.AssetName.ToString()
            .Contains(genderPath, StringComparison.Ordinal)));
    return ((ArrayPropertyData)matching["m_Outfits"]).Value.Cast<StructPropertyData>().ToArray();
}
