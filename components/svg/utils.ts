import { BrazilIcon, EnglandIcon } from ".";

export default function getIcon(icon: string) {
  switch (icon) {
    case "pt":
      return BrazilIcon;
    case "en":
    default:
      return EnglandIcon;
  }
}
