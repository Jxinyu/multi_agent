
class Solution:
    def lengthOfLongestSubstring(self, s: str) -> int:
        front = 0
        rear = 1
        max_len = 1
        while rear < len(s):
            l = 1 + rear - front
            t = len(set(s[front:rear+1]))
            if l == t:
                max_len = max(max_len, l)
                rear += 1
            else:
                while (front <= rear) and ((len(set(s[front:rear+1]))) < (1 + rear - front)):
                    front += 1
                rear += 1
        return max_len

    def main_l(self, s: str):
        # 使用滑动窗口+哈希表实现  没完成
        d = {}
        right, left, max_len = self.l1(s, d, 0, 1, 0)
        return max_len

    def l1(self, s: str, d: dict, right: int, left: int, max_len: int):
        #l       r
        #  l       r
        #    l       r
        #      l       r
        #  a b c a b c b b
        max_len = max(max_len, right - left)
        if -1 < left < len(s):
            d[s[left]] = max(d.get(s[left], 0) - 1, 0)
        while right < len(s):
            d[s[right]] = d.get(s[right], 0) + 1
            if d[s[right]] > 1:
                right, left, max_len = self.l1(s, d, right + 1, left + 1, max_len)
            right += 1
        return right, left, max_len


if __name__ == '__main__':
    print(Solution().main_l("abcabcbdbacd"))
