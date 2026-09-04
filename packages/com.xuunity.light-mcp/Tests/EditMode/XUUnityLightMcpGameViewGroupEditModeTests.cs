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
        public void EveryFallbackGroupNameExistsInTheUnityGroupEnum()
        {
            var groupEnumType = RequireGroupEnumType();
            var names = Enum.GetNames(groupEnumType);

            Assert.Contains(
                XUUnityLightMcpGameViewUtility.DefaultGroupFallbackName,
                names,
                "Default Game View group fallback name is not a GameViewSizeGroupType member.");

            foreach (var entry in XUUnityLightMcpGameViewUtility.BuildTargetGroupFallbackNames)
            {
                Assert.Contains(
                    entry.GroupName,
                    names,
                    $"Game View group fallback name for build target {entry.Target} is not a GameViewSizeGroupType member.");
            }
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
    }
}
