using TMPro;
using UnityEditor;
using UnityEngine;
using XUUnity.LightMcp.Editor.Core;

namespace XUUnity.LightMcp.Editor.Tmp
{
    [InitializeOnLoad]
    internal static class XUUnityLightMcpTmpModule
    {
        static XUUnityLightMcpTmpModule()
        {
            XUUnityLightMcpUiComponentReaderRegistry.Register(new XUUnityLightMcpTmpComponentReader());
        }
    }

    internal sealed class XUUnityLightMcpTmpComponentReader : IXUUnityLightMcpUiComponentReader
    {
        public string BackendId => "textmeshpro";

        public bool TryDescribe(Component component, XUUnityLightMcpUiNode node)
        {
            if (component is TMP_InputField inputField)
            {
                node.has_text = true;
                node.text = inputField.text ?? "";
                node.text_source = "TMPro.TMP_InputField";
                return true;
            }

            if (component is not TMP_Text tmpText)
            {
                return false;
            }

            node.has_text = true;
            node.text = tmpText.text ?? "";
            node.text_source = "TMPro.TMP_Text";
            node.effective_alpha = Mathf.Clamp01(node.effective_alpha * tmpText.color.a);
            node.visible = node.active_in_hierarchy && node.effective_alpha > 0f;

            var fontAsset = tmpText.font;
            node.font = fontAsset != null ? fontAsset.name : "";
            node.font_resolved_status = fontAsset != null ? "resolved" : "unresolved";

            var material = tmpText.fontSharedMaterial;
            node.material = material != null ? material.name : "";
            node.material_resolved_status = material != null ? "resolved" : "unresolved";

            if (fontAsset != null && material == null)
            {
                node.material_resolved_status = "font_without_material";
            }

            return true;
        }
    }
}
