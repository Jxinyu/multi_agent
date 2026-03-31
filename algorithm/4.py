from typing import List


class Solution:
    def moveZeroes(self, nums: List[int]) -> None:
        """
        Do not return anything, modify nums in-place instead.
        """
        front = 0
        rear = 0
        while rear < len(nums):
            if nums[rear] == 0:
                rear += 1
                continue
            t = nums[front]
            nums[front] = nums[rear]
            nums[rear] = t
            front += 1
            rear += 1
        print(nums)


if __name__ == '__main__':
    s = Solution()
    s.moveZeroes([0,1,0,3,12])