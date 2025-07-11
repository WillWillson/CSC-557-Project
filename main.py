from typing import Dict, List, Optional, Tuple
import random
import argparse
import sys
from time import sleep

# -------------------------
# Shamir Secret Sharing (Erasure Code)
# -------------------------

_PRIME = 2**127 - 1  # Large prime for finite field arithmetic

def _eval_polynomial(coeffs: List[int], x: int, prime: int) -> int:
    """Evaluate polynomial with coefficients `coeffs` at point `x` modulo `prime`."""
    result = 0
    for power, coef in enumerate(coeffs):
        result = (result + coef * pow(x, power, prime)) % prime
    return result

def ECEnc(n: int, k: int, secret: int) -> List[Tuple[int, int]]:
    """Generate n shares (x, y) from secret with threshold k."""
    if not (0 <= secret < _PRIME):
        raise ValueError("Secret out of range")
    # Create a deterministic polynomial with secret as the constant term
    # Use the secret as seed for reproducible coefficients
    random.seed(secret)
    coeffs = [secret] + [random.randrange(_PRIME) for _ in range(k - 1)]
    # Generate n (x, y) shares by evaluating polynomial at x=1 to x=n
    shares = [(i, _eval_polynomial(coeffs, i, _PRIME)) for i in range(1, n + 1)]
    print(f"[ECEnc] Generated shares: {shares}")
    return shares

def _lagrange_interpolate(x: int, x_s: List[int], y_s: List[int], prime: int) -> int:
    """Lagrange interpolation to recover secret from shares."""
    total = 0
    k = len(x_s)
    for i in range(k):
        xi, yi = x_s[i], y_s[i]
        num, den = 1, 1
        for j in range(k):
            if i != j:
                xj = x_s[j]
                num = (num * (x - xj)) % prime
                den = (den * (xi - xj)) % prime
        inv_den = pow(den, prime - 2, prime)  # Compute modular inverse
        total = (total + yi * num * inv_den) % prime
    return total

def ECDec(n: int, k: int, shares: List[Tuple[int, int]]) -> int:
    """Recover secret from any k shares."""
    x_s, y_s = zip(*shares[:k])
    secret = _lagrange_interpolate(0, list(x_s), list(y_s), _PRIME)
    print(f"[ECDec] Recovered secret from {shares[:k]}: {secret}")
    return secret

# -------------------------
# Reliable Broadcast
# -------------------------

NODES: Dict[int, "OciorABAStarNode"] = {}  # Global registry of all nodes

class RBC:
    def __init__(self, owner: int):
        self.owner = owner

    def broadcast(self, share: Tuple[int, int]):
        # Broadcast a share to all nodes
        print(f"[RBC] Node {self.owner} broadcasting {share}")
        for node in NODES.values():
            node.on_rbc_delivery(self.owner, share)

# -------------------------
# Common Coin for Byzantine Agreement
# -------------------------

class CommonCoin:
    def __init__(self, n: int, t: int):
        self.n = n
        self.t = t
        self.coin_shares: Dict[int, int] = {}  # Node ID -> coin share
        self._coin_value: Optional[int] = None
        
    def contribute_share(self, node_id: int, round_num: int):
        """Each node contributes a deterministic share based on node ID and round"""
        # Use a simple but deterministic function for the coin share
        # In practice, this would use threshold signatures or VRF
        share = (node_id * 7 + round_num * 13) % 2
        self.coin_shares[node_id] = share
        print(f"[CommonCoin] Node {node_id} contributed share {share} for round {round_num}")
        self._try_compute_coin()
    
    def _try_compute_coin(self):
        """Compute coin value when we have enough shares"""
        if len(self.coin_shares) >= self.t + 1 and self._coin_value is None:
            # XOR all shares to get coin value (simple but effective)
            coin_value = 0
            for share in list(self.coin_shares.values())[:self.t + 1]:
                coin_value ^= share
            self._coin_value = coin_value
            print(f"[CommonCoin] Computed coin value: {self._coin_value}")
    
    def get_coin_value(self) -> Optional[int]:
        return self._coin_value
    
    def has_coin_value(self) -> bool:
        return self._coin_value is not None

# -------------------------
# Simplified ABBA with Common Coin
# -------------------------

class ABBA:
    def __init__(self, owner: int, n: int, t: int):
        self.owner = owner
        self.n = n
        self.t = t
        self.inputs: Dict[int, int] = {}  # sender_id -> vote
        self._output: Optional[int] = None
        self.common_coin = CommonCoin(n, t)
        self.coin_requested = False

    def input(self, sender: int, v: int):
        """Accept a binary vote from a sender"""
        if sender in self.inputs:
            return
        self.inputs[sender] = v
        print(f"[ABBA-{self.owner}] Received vote {v} from Node {sender}")
        
        # Contribute to common coin when we receive our first input
        if not self.coin_requested:
            self.common_coin.contribute_share(sender, 1)  # Simple round 1
            self.coin_requested = True
        
        self._try_decide()

    def _try_decide(self):
        """Try to reach consensus based on received votes"""
        if self._output is not None:
            return
            
        ones = sum(1 for v in self.inputs.values() if v == 1)
        zeros = sum(1 for v in self.inputs.values() if v == 0)
        total_votes = len(self.inputs)
        print(f"[ABBA-{self.owner}] Current votes: {ones} ones, {zeros} zeros, {total_votes} total")
        
        # Strong majority decisions
        if ones >= self.n - self.t:
            self._output = 1
            print(f"[ABBA-{self.owner}] Decided 1 (ones={ones} >= {self.n - self.t})")
        elif zeros >= self.n - self.t:
            self._output = 0
            print(f"[ABBA-{self.owner}] Decided 0 (zeros={zeros} >= {self.n - self.t})")
        elif total_votes >= self.n - self.t:
            # Use common coin for tie-breaking when we have enough votes
            if self.common_coin.has_coin_value():
                coin_value = self.common_coin.get_coin_value()
                print(f"[ABBA-{self.owner}] Using common coin value {coin_value} to break tie")
                if ones >= self.t + 1:
                    self._output = 1
                    print(f"[ABBA-{self.owner}] Decided 1 using coin (ones={ones} >= {self.t + 1})")
                elif zeros >= self.t + 1:
                    self._output = 0  
                    print(f"[ABBA-{self.owner}] Decided 0 using coin (zeros={zeros} >= {self.t + 1})")
                else:
                    # Fallback to coin value
                    self._output = coin_value
                    print(f"[ABBA-{self.owner}] Decided {coin_value} using coin fallback")

    def has_output(self) -> bool:
        """Check if this ABBA instance has made a decision"""
        return self._output is not None

    def get_output(self) -> Optional[int]:
        """Get the decision (0 or 1)"""
        return self._output

# -------------------------
# OciorABA⋆ Node
# -------------------------

class OciorABAStarNode:
    def __init__(self, node_id: int, n: int, t: int, is_byzantine: bool = False):
        self.id = node_id
        self.n = n
        self.t = t
        self.is_byzantine = is_byzantine
        # Votes from each node
        self.vi: Dict[int, Optional[int]] = {j: None for j in range(1, n + 1)}
        # Shares generated by this node
        self._shares: List[Tuple[int, int]] = []
        # Shares received before ready
        self.pending_shares: List[Tuple[int, Tuple[int, int]]] = []
        # Store shares received from other nodes
        self.rbc_shares: Dict[int, Tuple[int, int]] = {}

        self.rbc = RBC(node_id)
        # ABBA per sender
        self.abba: Dict[int, ABBA] = {j: ABBA(j, n, t) for j in range(1, n + 1)}
        # Final outputs from each ABBA instance
        self.abba_out: Dict[int, int] = {}
        # Store the final decision
        self.final_decision: Optional[int] = None
        # Track if protocol has completed
        self.protocol_complete = False

        NODES[node_id] = self

    def propose(self, secret: int) -> None:
        # Propose a secret by encoding it and broadcasting one share
        print(f"\n[Node {self.id}] {'(BYZANTINE) ' if self.is_byzantine else ''}Proposing secret {secret}")
        
        if self.is_byzantine:
            # Byzantine behavior: propose a different/corrupted secret
            corrupted_secret = (secret + self.id * 1000) % _PRIME  # Different secret per Byzantine node
            self._shares = ECEnc(self.n, self.t + 1, corrupted_secret)
            print(f"[Node {self.id}] BYZANTINE: Using corrupted secret {corrupted_secret} instead of {secret}")
        else:
            self._shares = ECEnc(self.n, self.t + 1, secret)
        
        x_i, y_i = self._shares[self.id - 1]
        self.rbc.broadcast((x_i, y_i))
        
        # Process any pending shares now that we have our own shares
        for sender, share in self.pending_shares:
            self._process_share(sender, share)
        self.pending_shares.clear()

    def on_rbc_delivery(self, sender: int, share: Tuple[int, int]) -> None:
        # Store the delivered share
        self.rbc_shares[sender] = share

        # Handle a received share from another node
        if not self._shares:
            print(f"[Node {self.id}] Received share from Node {sender}, storing for later processing")
            self.pending_shares.append((sender, share))
            return
        
        self._process_share(sender, share)
    
    def _process_share(self, sender: int, share: Tuple[int, int]) -> None:
        # Process a share from a sender
        x_j, y_jj = share
        x_i_j, y_i_j = self._shares[sender - 1]
        assert x_i_j == x_j  # Ensure x values match
        print(f"[Node {self.id}] Processing share from Node {sender}: {share}")
        print(f"[Node {self.id}] Expected share for Node {sender}: ({x_i_j}, {y_i_j})")
        
        if self.is_byzantine:
            # Byzantine behavior: vote randomly instead of honestly
            vote = random.choice([0, 1])
            print(f"[Node {self.id}] BYZANTINE: Random vote for Node {sender} = {vote}")
        else:
            # Honest behavior: vote based on whether share matches
            vote = 1 if y_jj == y_i_j else 0  # Vote 1 if share matches expected
            print(f"[Node {self.id}] Vote for Node {sender} = {vote}")
        
        self.vi[sender] = vote
        
        # Send vote to all nodes' ABBA instances for this sender
        for node in NODES.values():
            node.abba[sender].input(self.id, vote)
        
        # Check for new ABBA decisions after each vote
        self._process_abba()

    def _process_abba(self):
        # Process ABBA decisions
        new_outputs = False
        for j, ab in self.abba.items():
            if j not in self.abba_out and ab.has_output():
                self.abba_out[j] = ab.get_output()  # type: ignore
                print(f"[Node {self.id}] ABBA[{j}] output = {self.abba_out[j]}")
                new_outputs = True
        
        # Aggressive termination: inject default votes for undecided ABBA
        self._inject_default_votes()
        
        # Check if all ABBA instances have decided
        if len(self.abba_out) == self.n:
            self._finalize()
    
    def _inject_default_votes(self):
        # Inject default votes (0) for undecided ABBA instances
        if len(self.abba_out) > 0:  # As soon as any ABBA decides
            for j in range(1, self.n + 1):
                if j not in self.abba_out:
                    # Always inject 0 to force decision
                    self.abba[j].input(self.id, 0)

    def _finalize(self):
        # Finalize the decision based on ABBA outputs
        Aones = {j for j, v in self.abba_out.items() if v == 1}
        print(f"[Node {self.id}] Aones = {Aones}")

        if len(Aones) < self.t + 1:
            print(f"[Node {self.id}] Decides ⊥")  # Not enough valid shares
            self.final_decision = None  # Store the failure decision
            self.protocol_complete = True
            return
        
        Bones = sorted(Aones)[: self.t + 1]  # Select t+1 valid shares
        print(f"[Node {self.id}] Bones = {Bones}")

        missing = [j for j in Bones if j not in self.rbc_shares]
        if missing:
            self.protocol_complete = True
            return
        
        shares = [self._shares[j - 1] for j in Bones]
        recovered = ECDec(self.n, self.t + 1, shares)  # Reconstruct the secret
        print(f"[Node {self.id}] Decides {recovered}")
        self.final_decision = recovered  # Store the successful decision
        self.protocol_complete = True

# Funtion for passing in command line arguments

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ocior ABA⋆ Algorithm 1 Demo")
    parser.add_argument("-n", "--nodes", type=int, default=4,
                        help="Number of nodes (default: 4)")
    parser.add_argument("-t", "--faults", type=int, default=1,
                        help="Maximum faulty nodes tolerated (default: 1)")
    parser.add_argument('-s', '--secret', type=int, default=2025,
                        help="Secret to be proposed by nodes (default: 2025)")
    parser.add_argument('--byzantine-behavior', choices=['random-vote', 'corrupt-share', 'both'], 
                        default='both',
                        help="Type of Byzantine behavior (default: both)")
    return parser.parse_args()

if __name__ == "__main__":
    cfg = parse_args()
    n, t, secret = cfg.nodes, cfg.faults, cfg.secret

    if n < 3 * t + 1:
        sys.exit("Error: n must be at least 3t + 1 for Byzantine fault tolerance")

    NODES.clear()
    
    # Designate first t nodes as Byzantine
    byzantine_nodes = set(range(1, t + 1))
    
    for i in range(1, n + 1):
        is_byzantine = i in byzantine_nodes
        OciorABAStarNode(i, n=n, t=t, is_byzantine=is_byzantine)

    # Have all nodes propose the same secret (Byzantine nodes will corrupt it)
    print(f"\n=== Simulation Start: n={n}, t={t}, secret={secret} ===")
    print(f"Byzantine nodes: {sorted(byzantine_nodes)} | Honest nodes: {sorted(set(range(1, n+1)) - byzantine_nodes)}")
    
    for i in range(1, n + 1):
        NODES[i].propose(secret)
    
    # Wait for all nodes to complete the protocol
    timeout = 5.0  # seconds
    interval = 0.1
    elapsed = 0.0
    while not all(node.protocol_complete for node in NODES.values()) and elapsed < timeout:
        # Continuously process ABBA decisions and inject defaults
        for node in NODES.values():
            if not node.protocol_complete:
                node._process_abba()
        
        sleep(interval)
        elapsed += interval

    # Check for hang
    if not all(node.protocol_complete for node in NODES.values()):
        print("Error: Protocol did not complete on all nodes within timeout.")
        incomplete_nodes = [i for i in range(1, n+1) if not NODES[i].protocol_complete]
        print(f"Incomplete nodes: {incomplete_nodes}")
        for i in incomplete_nodes:
            node = NODES[i]
            print(f"[Node {i}] ABBA outputs: {node.abba_out}")
        sys.exit(1)

    # Display final results
    print(f"\n=== Final Results ===")
    print(f"Original secret: {secret}")
    
    print(f"\nNode decisions:")
    for i in range(1, n + 1):
        node = NODES[i]
        status = "COMPLETE" if node.protocol_complete else "INCOMPLETE"
        decision = node.final_decision if node.final_decision is not None else "⊥ (failure)"
        node_type = "(BYZANTINE)" if node.is_byzantine else "(HONEST)"
        print(f"  Node {i} {node_type}: {decision} [{status}]")
    
    # Check consensus from the perspective of each node
    # In reality, nodes don't know which other nodes are Byzantine
    all_decisions = [node.final_decision for node in NODES.values() 
                    if node.final_decision is not None]
    
    # Count occurrences of each decision
    from collections import Counter
    decision_counts = Counter(all_decisions)
    
    print(f"\nDecision analysis:")
    for decision, count in decision_counts.items():
        print(f"  Decision {decision}: {count} nodes")
    
    # Protocol-level consensus: majority among all responding nodes
    if not all_decisions:
        print(f"\n✗ No nodes reached a decision")
    elif len(decision_counts) == 1:
        # All nodes that decided agree
        consensus_value = list(decision_counts.keys())[0]
        print(f"\n✓ Universal consensus: {consensus_value}")
        print(f"  All {len(all_decisions)} deciding nodes agree")
    else:
        # Check if there's a clear majority (> n/2)
        max_count = max(decision_counts.values())
        majority_threshold = (n + 1) // 2  # More than half of all nodes
        
        if max_count >= majority_threshold:
            majority_decision = [decision for decision, count in decision_counts.items() 
                               if count == max_count][0]
            print(f"\n✓ Majority consensus: {majority_decision}")
            print(f"  {max_count}/{n} nodes agree (threshold: {majority_threshold})")
        else:
            print(f"\n✗ No consensus: No decision has majority")
            print(f"  Highest count: {max_count}/{n} (threshold: {majority_threshold})")
    
    # Also show the theoretical honest-node consensus for analysis
    honest_decisions = [node.final_decision for node in NODES.values() 
                       if not node.is_byzantine and node.final_decision is not None]
    if honest_decisions and len(set(honest_decisions)) == 1:
        print(f"\n[Analysis] Honest nodes consensus: {honest_decisions[0]} ({len(honest_decisions)}/{n-t} honest nodes)")