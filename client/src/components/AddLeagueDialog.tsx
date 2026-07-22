import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

type Props = {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
};

export default function AddLeagueDialog({ open, onClose, onAdded }: Props) {
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [sportType, setSportType] = useState<"matchup" | "event">("matchup");

  const addMutation = trpc.leagues.add.useMutation({
    onSuccess: () => {
      toast.success(`League "${displayName}" added successfully`);
      onAdded();
      onClose();
      setName("");
      setDisplayName("");
      setSportType("matchup");
    },
    onError: (err) => {
      toast.error(`Failed to add league: ${err.message}`);
    },
  });

  const handleSubmit = () => {
    if (!name.trim() || !displayName.trim()) {
      toast.error("Please fill in all fields");
      return;
    }
    addMutation.mutate({ name, displayName, sportType });
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="bg-card border-border text-card-foreground max-w-md">
        <DialogHeader>
          <DialogTitle className="text-foreground">Add New Sport / League</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label className="text-sm text-muted-foreground">Short Code (e.g. NHRA, PLL)</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value.toUpperCase())}
              placeholder="MLB"
              className="bg-input border-border text-foreground"
              maxLength={20}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm text-muted-foreground">Full Display Name</Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Major League Baseball"
              className="bg-input border-border text-foreground"
              maxLength={128}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-sm text-muted-foreground">Sport Type</Label>
            <Select value={sportType} onValueChange={(v) => setSportType(v as "matchup" | "event")}>
              <SelectTrigger className="bg-input border-border text-foreground">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-popover border-border">
                <SelectItem value="matchup">
                  Matchup (Home vs Away — e.g. MLB, NHL, NFL)
                </SelectItem>
                <SelectItem value="event">
                  Event (Single event — e.g. NHRA, Golf, Fishing)
                </SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {sportType === "matchup"
                ? "Matchup leagues have a home team and away team per game."
                : "Event leagues have a single event name (no home/away teams)."}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} className="border-border">
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={addMutation.isPending}>
            {addMutation.isPending ? "Adding..." : "Add League"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

