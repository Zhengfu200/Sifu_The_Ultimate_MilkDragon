// Local reference poses only. Never include extracted game animations in releases.
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Objects.Core.Math;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion.Animations;
using Newtonsoft.Json;

if (args.Length < 3) throw new ArgumentException("AnimationAudit <paks> <output> <package>...");
using var provider = new DefaultFileProvider(args[0], SearchOption.TopDirectoryOnly, true, new VersionContainer(EGame.GAME_UE4_26));
provider.Initialize();
var key = Environment.GetEnvironmentVariable("SIFU_AES");
if (!string.IsNullOrEmpty(key)) provider.SubmitKey(new FGuid(), new FAesKey(key));
provider.Mount();
Directory.CreateDirectory(args[1]);
object Transform(FTransform t) => new { t = new[] { t.Translation.X, t.Translation.Y, t.Translation.Z },
    q = new[] { t.Rotation.X, t.Rotation.Y, t.Rotation.Z, t.Rotation.W },
    s = new[] { t.Scale3D.X, t.Scale3D.Y, t.Scale3D.Z } };
foreach (var path in args.Skip(2))
{
    var seq = provider.LoadPackageObjects(path.Replace("/Game/", "Sifu/Content/")).OfType<UAnimSequence>().First();
    var skeleton = seq.Skeleton.Load<USkeleton>();
    var converted = skeleton.ConvertAnims(seq).Sequences[0];
    var source = skeleton.ReferenceSkeleton.FinalRefBonePose;
    if (!seq.RetargetSource.IsNone && skeleton.AnimRetargetSources.TryGetValue(seq.RetargetSource, out var pose))
        source = pose.ReferencePose;
    var bones = skeleton.ReferenceSkeleton.FinalRefBoneInfo;
    var references = bones.Select((b, i) => new { name = b.Name.Text, mode = skeleton.BoneTree[i].ToString(), transform = Transform(source[i]) });
    var samples = Enumerable.Range(0, 13).Select(i => (float)Math.Round((converted.NumFrames - 1) * i / 12.0)).Distinct();
    var frames = new List<object>();
    foreach (var f in samples)
    {
        var samplesAtFrame = new List<object>();
        for (var i = 0; i < bones.Length; i++)
        {
            var pos = source[i].Translation;
            var rot = source[i].Rotation;
            var scale = source[i].Scale3D;
            var keyed = i < converted.Tracks.Count && converted.Tracks[i] != null && converted.Tracks[i].HasKeys();
            if (keyed) converted.Tracks[i].GetBoneTransform(f, converted.NumFrames, ref rot, ref pos, ref scale);
            samplesAtFrame.Add(new { name = bones[i].Name.Text, keyed,
                t = new[] { pos.X, pos.Y, pos.Z }, q = new[] { rot.X, rot.Y, rot.Z, rot.W }, s = new[] { scale.X, scale.Y, scale.Z } });
        }
        frames.Add(new { frame = f, bones = samplesAtFrame });
    }
    var result = new { name = seq.Name, source = path, retargetSource = seq.RetargetSource.Text,
        additive = seq.AdditiveAnimType.ToString(), numFrames = converted.NumFrames, fps = converted.FramesPerSecond,
        reference = references, frames };
    File.WriteAllText(Path.Combine(args[1], seq.Name + ".anim.json"), JsonConvert.SerializeObject(result, Formatting.Indented));
    Console.WriteLine($"{seq.Name}: {converted.NumFrames} frames, {seq.RetargetSource}, {seq.AdditiveAnimType}");
}
