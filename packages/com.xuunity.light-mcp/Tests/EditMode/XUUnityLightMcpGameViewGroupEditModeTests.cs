using System;
using NUnit.Framework;
using XUUnity.LightMcp.Editor.Helpers;

namespace XUUnity.LightMcp.Tests.EditMode
{
    [Category("XUUnity.MCP.SelfTest")]
    [Category("XUUnity.MCP.EditMode")]
    [Category("XUUnity.MCP.Fast")]
    public sealed class XUUnityLightMcpGameViewGroupEditModeTests
    {
        static Type RequireGroupEnumType()
        {
            var groupEnumType = Type.GetType("UnityEditor.GameViewSizeGroupType,UnityEditor");
            Assert.IsNotNull(groupEnumType, "UnityEditor.GameViewSizeGroupType is not available in this editor version.");
            return groupEnumType;
        }

        [Test]
        public void ProbeResolvesTheActiveGroupForTheCurrentBuildTarget()
        {
            var probe = XUUnityLightMcpGameViewUtility.ProbeReflectionSurface();

            Assert.IsTrue(
                probe.supported,
                $"Game View reflection probe failed for the active build target: {probe.reason}");
        }

        [Test]
        public void UnityConverterFallbackResolvesTheActiveGroupOnThisEditor()
        {
            var converted = XUUnityLightMcpGameViewUtility.ConvertActiveBuildTargetToGroupType(out var reason);

            Assert.IsNotNull(
                converted,
                $"Unity's own BuildTargetGroupToGameViewSizeGroup must stay callable as the resolver fallback: {reason}");
            Assert.That(reason, Is.Empty);
            Assert.IsTrue(
                RequireGroupEnumType().IsInstanceOfType(converted),
                "the fallback must return a GameViewSizeGroupType value");
        }

        [Test]
        public void GroupNameMatchAcceptsTheLegacyIosAliasAndRejectsForeignGroups()
        {
            Assert.IsTrue(XUUnityLightMcpGameViewUtility.GroupNameMatches("iPhone", "iOS"));
            Assert.IsTrue(XUUnityLightMcpGameViewUtility.GroupNameMatches("iOS", "iPhone"));
            Assert.IsTrue(XUUnityLightMcpGameViewUtility.GroupNameMatches("android", "Android"));
            Assert.IsFalse(XUUnityLightMcpGameViewUtility.GroupNameMatches("Android", "iOS"));
            Assert.IsFalse(XUUnityLightMcpGameViewUtility.GroupNameMatches("iPhone", "Standalone"));
        }

        [Test]
        public void DescribeGroupTypeReportsTheUnityEnumMemberName()
        {
            var groupEnumType = RequireGroupEnumType();

            foreach (var name in Enum.GetNames(groupEnumType))
            {
                var value = Enum.Parse(groupEnumType, name);
                Assert.AreEqual(name, XUUnityLightMcpGameViewUtility.DescribeGroupType(value));
            }
        }

        [Test]
        public void FixedResolutionIsAGameViewSizeTypeMemberOnThisEditor()
        {
            var sizeTypeEnum = Type.GetType("UnityEditor.GameViewSizeType,UnityEditor");
            Assert.IsNotNull(sizeTypeEnum, "UnityEditor.GameViewSizeType is not available in this editor version.");

            Assert.Contains(
                XUUnityLightMcpGameViewUtility.FixedResolutionSizeTypeName,
                Enum.GetNames(sizeTypeEnum),
                "custom Game View size creation parses this member name, so it must exist");
        }
    }
}
