// Light, dark or the system's: a reader's preference, never the document's.
import { useState } from "react";
import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { chooseTheme, storedTheme, type ThemeChoice } from "@/app/theme";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const CHOICES: { value: ThemeChoice; label: string; Icon: typeof SunIcon }[] = [
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
  { value: "system", label: "System", Icon: MonitorIcon },
];

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon-sm" aria-label="Colour theme" />}
      >
        <SunIcon className="dark:hidden" />
        <MoonIcon className="hidden dark:block" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuRadioGroup
          value={choice}
          onValueChange={(value: ThemeChoice) => {
            setChoice(value);
            chooseTheme(value);
          }}
        >
          {CHOICES.map(({ value, label, Icon }) => (
            <DropdownMenuRadioItem key={value} value={value} closeOnClick>
              <Icon />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
